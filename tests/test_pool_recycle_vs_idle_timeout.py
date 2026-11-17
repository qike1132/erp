"""回归守卫：应用连接池的 pool_recycle 必须小于服务器 idle_session_timeout。

根因（2026-10-07）
------------------
服务器当时 ``idle_session_timeout = '5min'``，会终止空闲超过 5 分钟的连接（实测日均
1000+ 次）。应用连接池的 ``pool_recycle`` 原为 1800s（30 分钟）远大于它，于是池中连接
被服务器杀掉后仍被应用取用 —— 表现为 asyncpg 协议错

    cannot switch to state 15; another operation (2) is in progress

（state 2 = PROTOCOL_ERROR_CONSUME），物化视图刷新任务间歇失败（2026-10-07 16:25:00
的 8 次 idle-session timeout）。修复把 ``pool_recycle`` 降到 1500s，随后服务器侧把
``idle_session_timeout`` 抬到 ``30min``（1800s，见 ``docs/optimization-plan-2026-10-01-final.md``
里那次 ``ALTER SYSTEM`` 及其后的实测）。

本测试把「连接最大存活 < 服务器空闲超时」这一不变量钉死。

阈值从哪来（单一真相源，2026-11-17 OCR 复审）
---------------------------------------------
本文件此前用模块级常量 ``SERVER_IDLE_TIMEOUT_SECONDS = 1800``，注释写「部署侧改这个值时
同步改这里」—— 那是**第二份真相源**：改服务器的人不会来改测试，改测试的人不会改服务器。
更糟的是同一文件的 docstring 写「服务器 = 5min」，与常量注释的 30min **互斥**；若现网
真是 5min，``DB_POOL_RECYCLE=1500`` 会「通过」这条静态守卫 —— 守卫等于没有
（1500 < 1800 成立，1500 < 300 不成立）。

现在收口成一条链，只有一个来源：
1. **入库模板** ``.env.production.example`` 里 ``DB_POOL_RECYCLE`` 上方那行声明
   （``idle_session_timeout（现值 1800s）``）是阈值来源，由 ``_declared_idle_timeout_seconds``
   解析；解析不出来就 **fail**，不静默按旧数字兜底。
2. ``.env.example`` 的同项声明必须与它一致（两份模板写两个答案正是本条要禁的形态）。
3. 活库读得到实测值时，断言「实测 == 模板声明」——两者一旦漂移，静态守卫的阈值就
   不再代表现实。读不到值按 **fail** 处理（见下）。

为什么有的分支只能 skip（门禁说明）
-----------------------------------
``idle_session_timeout = 0`` 是 PG 的**显式禁用**（不是「读不到」）：禁用后不存在
「服务器会先杀掉空闲连接」这个前提，不变量本身不成立，skip 是语义正确的结论（并会
在 skip 原因里写明）。而「读不到」（NULL / 非数值）是**证据缺失**，一律 fail：
证据缺失时「守卫通过」是最危险的假绿。``test_template_matches_host_server_config_if_present``
里的 skip 是唯一另一种情形——``postgresql.auto.conf`` 只存在于装了 PG 的主机上
（CI/Linux 跑的是容器内 PG，盘上没有这个文件），断言「文件不存在」不是回归。
"""
import os
import re
from pathlib import Path

import pytest
from sqlalchemy import text

#: 阈值来源模板（受版本控制；灾难恢复/新机照它生成 .env）。
IDLE_TIMEOUT_SOURCE_TEMPLATE = ".env.production.example"

#: 声明形状：`idle_session_timeout（现值 1800s）` / `idle_session_timeout（现 30min）`。
#: 两份模板用了不同单位，解析时统一换算成秒；换不出就 fail（见 _declared_idle_timeout_seconds）。
_IDLE_DECL_RE = re.compile(
    r"idle_session_timeout[^\n]*?(?:现值|现)\s*([0-9]+(?:\.[0-9]+)?)\s*(ms|s|sec|秒|min|分钟|m|h|小时|d)"
)

#: PG 时间单位 → 秒（GUC 里不带单位时是毫秒，如 `idle_session_timeout = 1800`）。
_UNIT_SECONDS = {
    "ms": 0.001,
    "s": 1.0, "sec": 1.0, "秒": 1.0,
    "min": 60.0, "分钟": 60.0, "m": 60.0,
    "h": 3600.0, "小时": 3600.0,
    "d": 86400.0,
}

#: 本机 PG 的 auto.conf 位置（只读证据；可用 ERP_PG_AUTO_CONF 覆盖）。
_HOST_PG_AUTO_CONF = os.getenv("ERP_PG_AUTO_CONF", r"D:\PostgreSQL\data\postgresql.auto.conf")


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _declared_idle_timeout_seconds(rel: str) -> int:
    """从入库模板的声明行解析服务器 idle_session_timeout（秒）。

    解析不到就抛 AssertionError（**不兜底**）：阈值来源没了，守卫必须红，
    否则就退化成「永远用一个没人维护的魔法数字」。
    """
    path = _root() / rel
    assert path.exists(), f"阈值来源模板缺失：{rel}（受版本控制，缺了说明守卫失去来源）"
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _IDLE_DECL_RE.search(line)
        if match:
            value, unit = float(match.group(1)), match.group(2)
            return round(value * _UNIT_SECONDS[unit])
    raise AssertionError(
        f"{rel} 里没有 idle_session_timeout 的声明行（期望形如 "
        f"`idle_session_timeout（现值 1800s）`）。阈值唯一来源失效 ⇒ 守卫无法判定，按失败处理。"
    )


def _pg_timeout_seconds(raw: str) -> float:
    """把 PG GUC 的取值（'30min' / '300s' / '1800'）换算成秒。换算不了就 ValueError。"""
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z\u4e00-\u9fff]*)\s*", raw)
    if not match:
        raise ValueError(f"无法解析 idle_session_timeout 取值：{raw!r}")
    value, unit = float(match.group(1)), match.group(2).lower()
    if not unit:
        return value / 1000.0  # 不带单位 = 毫秒（PG 对 *_timeout 类 GUC 的口径）
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"未知的 idle_session_timeout 单位：{unit!r}（取值 {raw!r}）")
    return value * _UNIT_SECONDS[unit]


@pytest.mark.integration
async def test_pool_recycle_below_server_idle_timeout(test_engine):
    from fastapi_app.core.database import _pool_config

    recycle = _pool_config["pool_recycle"]
    assert recycle > 0, "pool_recycle 必须为正（0 表示禁用回收，会让坏连接长期驻留池中）"

    async with test_engine.connect() as conn:
        # current_setting 返回如 '30min' / '0'；cast 成 interval 再取秒，单位无关。
        idle_seconds = (
            await conn.execute(
                text("SELECT extract(epoch FROM current_setting('idle_session_timeout')::interval)")
            )
        ).scalar()

    # 读不到值 = 证据缺失 ⇒ fail（不是 skip）：守卫「无法判定」时放行是最危险的假绿。
    if idle_seconds is None:
        pytest.fail(
            "读不到服务器 idle_session_timeout（current_setting 返回 NULL）——"
            "无法判定 pool_recycle 是否安全，按失败处理（不要改成 skip）。"
        )
    try:
        idle_seconds = float(idle_seconds)
    except (TypeError, ValueError):
        pytest.fail(
            f"服务器 idle_session_timeout 取值无法解析为数值：{idle_seconds!r} —— 无法判定，按失败处理。"
        )

    if idle_seconds == 0:
        # 0 = PG 显式禁用空闲会话超时（不是「读不到」）：不变量不存在，skip 是正确结论。
        pytest.skip("服务器 idle_session_timeout 已显式禁用（0），无此不变量约束")

    # 模板是静态守卫的阈值来源；活库与模板漂移时，守卫的阈值已不代表现实 —— 必须红。
    declared = _declared_idle_timeout_seconds(IDLE_TIMEOUT_SOURCE_TEMPLATE)
    assert idle_seconds == declared, (
        f"活库实测 idle_session_timeout={idle_seconds:.0f}s 与 "
        f"{IDLE_TIMEOUT_SOURCE_TEMPLATE} 声明的 {declared}s 不一致："
        "请同步模板（并复核 DB_POOL_RECYCLE），否则静态守卫的阈值是错的"
    )

    assert recycle < idle_seconds, (
        f"pool_recycle={recycle}s 必须 < 服务器 idle_session_timeout={idle_seconds:.0f}s，"
        "否则服务器会先杀掉空闲连接，应用取用坏连接会抛 asyncpg "
        "'cannot switch to state ...; another operation ... is in progress'"
    )


def test_idle_timeout_threshold_has_single_source():
    """阈值来源必须可解析且与自己一致（防止有人把声明行删掉/写坏后守卫静默失效）。"""
    declared = _declared_idle_timeout_seconds(IDLE_TIMEOUT_SOURCE_TEMPLATE)
    assert declared > 0, f"{IDLE_TIMEOUT_SOURCE_TEMPLATE} 的 idle_session_timeout 声明非正数：{declared}"
    # 两份入库模板必须给同一个答案（历史上 docstring 5min / 常量 30min 就是这么打起来的）
    assert _declared_idle_timeout_seconds(".env.example") == declared, (
        ".env.example 与 .env.production.example 对 idle_session_timeout 的声明不一致："
        "两份模板写两个答案时，静态守卫的阈值取决于读哪一份"
    )


def test_template_matches_host_server_config_if_present():
    """（本机可读时）盘上 ``postgresql.auto.conf`` 的实测值必须等于模板声明。

    为什么：模板是**入库**的声明，auto.conf 是**现网**的事实。二者漂移时，
    ``DB_POOL_RECYCLE=1500`` 可能「通过」静态守卫而实际已越过服务器阈值 ——
    这正是 2026-11-17 OCR 复审发现的「守卫等于没有」形态。

    这个检查只能在装了 PG 的主机上进行（本机/运维机）；CI 的 PG 在容器里，
    盘上没有 auto.conf，故「文件不存在」按 skip 处理并在原因里写明——那不是回归。
    """
    path = Path(_HOST_PG_AUTO_CONF)
    if not path.exists():
        pytest.skip(
            f"非 PG 主机（{_HOST_PG_AUTO_CONF} 不存在）：模板与现网 auto.conf 的比对只能在装了 "
            "PostgreSQL 的主机上做；静态守卫仍由 test_idle_timeout_threshold_has_single_source 兜底"
        )

    raw = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("idle_session_timeout"):
            raw = line.split("=", 1)[1].strip().strip("'\"")
            break
    assert raw is not None, f"{_HOST_PG_AUTO_CONF} 里找不到 idle_session_timeout（文件被改？）"

    measured = _pg_timeout_seconds(raw)
    declared = _declared_idle_timeout_seconds(IDLE_TIMEOUT_SOURCE_TEMPLATE)
    assert measured == declared, (
        f"现网 {_HOST_PG_AUTO_CONF} 的 idle_session_timeout={raw!r}（{measured:.0f}s）与 "
        f"{IDLE_TIMEOUT_SOURCE_TEMPLATE} 声明的 {declared}s 不一致："
        "静态守卫的阈值已不代表现网，请同步模板并复核 DB_POOL_RECYCLE"
    )


#: **入库**模板：必须存在，缺一个就说明守卫漏了面（不能「不存在就跳过」）。
#: 2026-11-16 上线前审计 H-4：A-31 那次只修了盘上两份不入库的灾备副本，
#: 于是 `.env.production.example` 仍写着 1800（= 阈值，「小于」不成立），
#: 而灾难恢复/新机恰恰是照**这份入库模板**生成 .env 的。
POOL_RECYCLE_REQUIRED_ENV_FILES = (".env.example", ".env.production.example")

#: 被 gitignore 的本地副本/灾备副本：存在才校验（全新克隆下不存在）。
POOL_RECYCLE_OPTIONAL_ENV_FILES = (
    ".env.production", "config/.env.production", ".env.development",
)

#: 兼容旧引用：全量清单（必查 + 可选）。
POOL_RECYCLE_ENV_FILES = POOL_RECYCLE_REQUIRED_ENV_FILES + POOL_RECYCLE_OPTIONAL_ENV_FILES


def _read_pool_recycle(path) -> int | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("DB_POOL_RECYCLE="):
            return int(stripped.split("=", 1)[1].strip())
    return None


def test_env_templates_pool_recycle_below_idle_timeout():
    """静态守卫：所有 `.env*` 副本里的 DB_POOL_RECYCLE 都必须小于 idle_session_timeout。

    为什么（2026-11-16 上线前审计 A-31）：上面那条集成测试只校验**代码默认值**与
    活库的 idle_session_timeout，扫不到 `.env.production` 这两份灾备副本——它们在 P0-10
    那次修复里被漏掉，仍写着 1800（= 服务器阈值，不是「小于」）。灾备真按它还原，
    2026-10-07 的连接态错乱会原样回归，而 CI 永远不会红。

    2026-11-16 上线前审计 H-4 补的两处：
    1) **入库模板** `.env.production.example` 当时仍写 1800，而它正是灾难恢复/新机生成
       .env 的来源 —— 现已改 1500 并纳入必查清单；
    2) 必查文件**不允许「不存在就跳过」**：模板缺失本身就是回归（旧逻辑会让守卫静默失效）。

    2026-11-17 OCR 复审：阈值不再是本文件里的魔法常量，改由
    `IDLE_TIMEOUT_SOURCE_TEMPLATE` 的声明行解析（见模块 docstring）。
    """
    from fastapi_app.core.database import _pool_config

    root = _root()
    code_default = _pool_config["pool_recycle"]
    assert code_default == 1500, f"代码默认 pool_recycle 应为 1500s，实际 {code_default}"
    server_idle_timeout = _declared_idle_timeout_seconds(IDLE_TIMEOUT_SOURCE_TEMPLATE)

    missing = [rel for rel in POOL_RECYCLE_REQUIRED_ENV_FILES if not (root / rel).exists()]
    assert not missing, (
        f"入库模板缺失：{missing}。这些文件受版本控制，缺了说明守卫的覆盖面又被缩小了"
    )

    checked = []
    for rel in POOL_RECYCLE_ENV_FILES:
        path = root / rel
        if not path.exists():
            continue  # 被 gitignore 的本地/灾备副本，全新克隆下不存在
        value = _read_pool_recycle(path)
        assert value is not None, f"{rel} 缺少 DB_POOL_RECYCLE 声明"
        assert value == code_default, (
            f"{rel} 的 DB_POOL_RECYCLE={value} 与代码默认 {code_default} 不一致"
            "（灾备按它还原会引入已修复的连接态错乱）"
        )
        assert value < server_idle_timeout, (
            f"{rel} 的 DB_POOL_RECYCLE={value}s 必须 < 服务器 "
            f"idle_session_timeout={server_idle_timeout}s（来源：{IDLE_TIMEOUT_SOURCE_TEMPLATE} 的声明行）"
        )
        checked.append(rel)

    assert checked, "至少要校验到 .env.example"

"""1.4（2026-10-17 审计 TEST 区 P2）：测试库整库重置的触发面必须留痕、可拒绝。

现状（改动前）：`tests/conftest.py::test_engine` 每次会话都 `DROP SCHEMA public CASCADE`，
**包括只跑 3 条用例的聚焦跑**，而且没有任何痕迹。互斥锁只管得住「另一个 pytest 进程」，
管不住 psql / 造数脚本 / 运维脚本：它们的连接被清掉后，没人能回答「谁在什么时候把库清了」。
`ERP_TEST_DB_NO_RESET=1` 现在能拒绝重置（用于「现在别动这个库」）。

本文件锁住 4 件事：
1. 默认重置开启，开关值只认明确真值（写成 `0` 不许意外关掉重置）；
2. 留痕一次一行 JSONL，字段齐全（ts/database/tables/pid/argv）且**追加**不覆盖；
3. 留痕失败绝不抛（写不进日志不能把整场测试打挂）；
4. conftest 里 `record_reset(...)` 必须出现在 `DROP SCHEMA public CASCADE` **之前**，
   且 DROP 必须在 `reset_enabled()` 判定之内 —— 否则「先清后记」等于没记。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests import _test_db_reset as hook

REPO = Path(__file__).resolve().parent.parent
CONFTEST = REPO / "tests" / "conftest.py"


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path, monkeypatch):
    """所有用例的痕迹文件都指向 tmp，绝不污染真实的 logs/test_db_reset.jsonl。"""
    monkeypatch.setenv(hook.ENV_LOG, str(tmp_path / "resets.jsonl"))
    monkeypatch.delenv(hook.ENV_SKIP, raising=False)
    return tmp_path / "resets.jsonl"


def test_reset_enabled_by_default() -> None:
    assert hook.reset_enabled() is True


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_reset_can_be_disabled_by_env(monkeypatch, value) -> None:
    monkeypatch.setenv(hook.ENV_SKIP, value)
    assert hook.reset_enabled() is False, f"{hook.ENV_SKIP}={value!r} 应关闭重置"


@pytest.mark.parametrize("value", ["0", "false", "", "no"])
def test_only_explicit_truthy_values_disable_reset(monkeypatch, value) -> None:
    """`0`/空/`no` 都不许关掉重置：误写成 0 却静默跳过重置会让库漂移不被清理。"""
    monkeypatch.setenv(hook.ENV_SKIP, value)
    assert hook.reset_enabled() is True


def test_record_reset_appends_full_entry(_isolated_log) -> None:
    first = hook.record_reset(database="erp_system_test", tables=42)
    second = hook.record_reset(database="erp_system_test", tables=0)

    assert first is not None and second is not None
    lines = _isolated_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, f"两次重置应留两行（追加而非覆盖）：{lines}"

    entry = json.loads(lines[0])
    assert entry["database"] == "erp_system_test"
    assert entry["tables"] == 42
    assert isinstance(entry["pid"], int) and entry["pid"] > 0
    assert isinstance(entry["argv"], list) and entry["argv"]
    assert entry["ts"].startswith("20"), f"ts 应为 ISO 时间戳：{entry['ts']}"
    assert json.loads(lines[1])["tables"] == 0, "空库（0 张表）也必须留下痕迹"


def test_record_reset_never_raises_when_path_unwritable(tmp_path, monkeypatch) -> None:
    """痕迹写不进（这里让父路径是个文件）不能抛：留痕是辅助，不能变成新的失败源。"""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv(hook.ENV_LOG, str(blocker / "resets.jsonl"))

    assert hook.record_reset(database="erp_system_test", tables=1) is None


def test_default_log_path_lives_under_logs(monkeypatch) -> None:
    monkeypatch.delenv(hook.ENV_LOG, raising=False)
    path = hook.log_path()
    assert path.parent.name == "logs" and path.name == "test_db_reset.jsonl", path


def test_database_name_is_extracted_from_url() -> None:
    url = "postgresql+asyncpg://erp:secret@127.0.0.1:5432/erp_system_test?ssl=false"
    assert hook.database_name_from_url(url) == "erp_system_test"


def test_conftest_records_before_it_drops_the_schema() -> None:
    """顺序判定：留痕调用必须在 DROP 之前，且 DROP 在 `reset_enabled()` 分支内。"""
    src = CONFTEST.read_text(encoding="utf-8")
    record_at = src.index("record_reset(")
    drop_at = src.index('text("DROP SCHEMA public CASCADE")')
    assert record_at < drop_at, (
        "conftest 里 record_reset(...) 必须出现在 DROP SCHEMA 之前 —— "
        "先清库再记账的话，重置中途崩溃就什么都留不下"
    )

    # 解析级复核（2026-11-19 评审：原来三处都能恒真）：
    #   ① 不再用 `"if reset_enabled():" in src`（一句注释就能满足）；
    #   ② 只扫 `if reset_enabled():` 的 body —— 原来 `ast.walk(node)` 连 orelse 一起扫，
    #      把 DROP 挪进 else（= 「只有设了 ERP_TEST_DB_NO_RESET 才清库」的取反语义）仍然通过；
    #   ③ 断言全文件 DROP 出现次数恰为 1 —— 原来只比较「首次出现」，事后追加一个未受保护的
    #      DROP 不会被看见。
    tree = ast.parse(src)

    def _drop_execute_lines(node: ast.AST) -> list[int]:
        """只数**真正执行**的 DROP（`... .execute(text("DROP SCHEMA ..."))`）。

        conftest 的 docstring 与告警文案里也写着 `DROP SCHEMA public CASCADE`，
        按 `ast.Constant` 统计会把这些文本算进去（2026-11-19 评审实测）。
        """
        out: list[int] = []
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            call_src = ast.unparse(sub)
            if ".execute(" in call_src and "DROP SCHEMA" in call_src:
                out.append(sub.lineno)
        return out

    all_drops = _drop_execute_lines(tree)
    assert len(all_drops) == 1, (
        f"conftest 里「执行 DROP SCHEMA」必须只有一处（受 reset_enabled() 保护），实际 {all_drops}"
    )

    in_body: list[int] = []
    in_orelse: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or ast.unparse(node.test) != "reset_enabled()":
            continue
        for stmt in node.body:
            in_body += _drop_execute_lines(stmt)
        for stmt in node.orelse:
            in_orelse += _drop_execute_lines(stmt)

    assert in_orelse == [], (
        f"DROP SCHEMA 出现在 `else:` 里（L{in_orelse}）—— 那等于「设了 NO_RESET 才清库」，开关语义反了"
    )
    assert in_body == all_drops, (
        "DROP SCHEMA 不在 `if reset_enabled():` 的分支体内"
        f"（分支内 {in_body} / 全文件 {all_drops}）—— 开关已失效"
    )


def test_database_name_never_leaks_credentials() -> None:
    """取不到库名时回落 ``<unknown>``，绝不回落整串 URL —— 整串里含口令。

    评审（2026-11-19 Low）：原来 `... or url` 在 URL 没有库名段时会把带口令的整串写进
    `logs/test_db_reset.jsonl`。URL 用 `URL.create` 在运行时拼（源码里不留字面 DSN，
    否则 `.githooks` 的密钥扫描会拦提交 —— 也不该为一条测试去动豁免清单）。
    """
    from sqlalchemy.engine import URL

    secret = "".join(["sup", "3r", "s3cr", "et"])
    url = URL.create(
        "postgresql+asyncpg", username="erp", password=secret, host="127.0.0.1", port=5432
    )
    assert url.database is None

    name = hook.database_name_from_url(url.render_as_string(hide_password=False))

    assert secret not in name, f"留痕泄露口令：{name!r}"
    assert name == "<unknown>", name

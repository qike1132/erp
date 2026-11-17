"""删库前「服务确实已停」的终态断言回归锁（2026-11-17 OCR 复审）。

背景：`scripts/migrate/setup_on_target.ps1` / `install_on_target.ps1` 曾这么写——

    & $NssmExe stop $svc | Out-Null
    Write-Ok "Stopped $svc"          # ← 无条件成功宣告

NSSM **非提权调用会静默失败且退出码仍 0**（AGENTS §6.1-7，本机踩过），所以这行
`[OK]` 是假的；随后脚本仅凭 `Read-Host` 输入 `DROP` 就 `pg_terminate_backend` +
`DROP DATABASE`。服务还在跑时删库，等于强断正在进行的业务连接，且若随后的
`CREATE DATABASE` 失败，服务会对着一个不存在的库继续跑。

已按 `deploy/install_package.ps1:373-397` 的已验证形态修复：停完服务后用
`Get-Service` 逐个判 `Status -ne 'Stopped'`，收集 `$stillRunning`，非空则打印明细并
`exit 1`，且位置在 `pg_terminate_backend` / `DROP DATABASE` **之前**。

本文件用静态断言把三件事钉住（`.ps1` 无法在 pytest 里整体执行——它们会真的停服务、删库）：
1) 断言函数存在且按状态判定（不是看退出码/回显）；
2) 断言在 `pg_terminate_backend` / `DROP DATABASE` 之前被调用；
3) 老的「无条件 Write-Ok "Stopped $svc"」不再存在，且停机清单与断言用同一变量（不许分叉）。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SCRIPTS = (
    "scripts/migrate/setup_on_target.ps1",
    "scripts/migrate/install_on_target.ps1",
)

#: 停机清单的单一来源变量：停机循环与终态断言必须引用同一个，否则两处会漂移
#: （改了停机清单却漏改断言 = 断言对着一个不存在的服务名恒真）。
STOP_LIST_VAR = "$ErpLocalServices"


def _read(rel: str) -> str:
    path = REPO / rel
    assert path.exists(), f"{rel} 不存在：删库脚本被改名/搬走时该守卫不能静默失效"
    return path.read_text(encoding="utf-8")


def _assert_helper_body(text: str) -> str:
    match = re.search(
        r"function\s+Assert-ServicesStopped\s*\(\[string\[\]\]\$Names\)\s*\{(.*?)\n\}",
        text,
        re.S,
    )
    assert match, "缺少 Assert-ServicesStopped 终态断言函数"
    return match.group(1)


@pytest.mark.parametrize("rel", SCRIPTS)
def test_stop_assertion_judges_service_status(rel):
    """断言必须按 Get-Service 的 Status 终态判定，不能凭 nssm 退出码或回显。"""
    body = _assert_helper_body(_read(rel))
    assert "Get-Service" in body, "断言没查服务状态（NSSM 静默失败正是这么漏的）"
    assert "$stillRunning" in body, "断言没收集仍在跑的服务名单（报错时无从排查）"
    assert "'Stopped'" in body or '"Stopped"' in body, "断言没有与 'Stopped' 比较"
    assert re.search(r"if\s*\(\s*\$stillRunning\.Count\s*-gt\s*0\s*\)", body), \
        "断言没有在仍有服务运行时进入失败分支"
    assert "exit 1" in body, "断言失败时没有 exit 1（会继续删库）"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_stop_assertion_runs_right_before_drop_database(rel):
    """删库前必须**当场再断言一次**服务终态（不是只靠 Step 2 那次）。

    为什么用「最后一次调用」而不是「某次调用」：Step 2 停机时也有一次断言，
    只要求「存在一次且在 DROP 之前」的话，把 DROP 前那次删掉测试仍然绿——
    这样断言就退化成「Step 2 曾经断言过」，中间隔着解包/建角色几分钟，
    且 `-SkipStart` 时 Step 2 整段不执行。故这里取**最后一次**调用，
    要求它位于 DROP 的 `Read-Host` 确认之后、`pg_terminate_backend` 之前。
    """
    text = _read(rel)
    call = text.rfind(f"Assert-ServicesStopped {STOP_LIST_VAR}")
    assert call != -1, f"{rel} 没有调用 {STOP_LIST_VAR} 的终态断言"

    # 注意：必须锚在**语句**上。`pg_terminate_backend` 在断言上方那行注释里也出现了一次
    # （"否则 pg_terminate_backend 会强断…"），用裸词会锚到注释、把顺序比对测成恒真。
    confirm_at = text.find("Type DROP to continue")
    terminate_at = text.find("SELECT pg_terminate_backend")
    drop_at = text.find('DROP DATABASE $dbName"')
    assert confirm_at != -1 and terminate_at != -1 and drop_at != -1, (
        f"{rel} 未找到「DROP 确认 / pg_terminate_backend / DROP DATABASE」三处结构（脚本变了？）"
    )
    assert confirm_at < call, (
        "终态断言不在 DROP 确认之后：最后一次断言出现在确认之前，删库那一刻没人验服务状态"
    )
    assert call < terminate_at, "终态断言在 pg_terminate_backend 之后 —— 那时连接已被强断"
    assert call < drop_at, "终态断言在 DROP DATABASE 之后 —— 太晚了"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_no_unconditional_stopped_message(rel):
    """老的 `Write-Ok "Stopped $svc"` 必须消失：它把「发过停止命令」写成了「已停止」。"""
    text = _read(rel)
    assert 'Write-Ok "Stopped $svc"' not in text, \
        '仍有无条件成功宣告 Write-Ok "Stopped $svc"（NSSM 静默失败时这句是假的）'


@pytest.mark.parametrize("rel", SCRIPTS)
def test_stop_list_single_source(rel):
    """停机循环与终态断言必须共用同一个清单变量，禁止各写一份枚举。"""
    text = _read(rel)
    assert re.search(
        re.escape(STOP_LIST_VAR) + r"\s*=\s*@\(\s*\"erp-prod\"\s*,\s*\"erp-arq\"\s*\)", text
    ), f"{rel} 缺少 {STOP_LIST_VAR} 停机清单定义"
    assert f"foreach ($svc in {STOP_LIST_VAR})" in text, \
        f"{rel} 的停机循环没用 {STOP_LIST_VAR}（清单与断言会漂移）"

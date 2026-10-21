# tests/test_n_plus_one_whitelist_zombie_keys.py
"""回归锁：N+1 白名单里失效的豁免键必须被门禁发现，不能静默烂掉。

背景（2026-10-21，2026-10-17 审计 Z05-R12 余量）
------------------------------------------------
``scripts/allowed_n_plus_one.yaml`` 里一直豁免
``fastapi_app/services/backup/incremental.py``——该模块在 2026-10-12「全量only」重构中
已整文件删除（`docs/superpowers/plans/2026-10-12-full-only-backup.md`）。扫描器按
「键 ∈ 白名单集合」匹配，键指向的文件存不存在根本没人核对，于是这条豁免**只是历史噪声**。

危险的不是噪声，是这类键的通用形态：文件被改名/函数被改名/行号漂移后，豁免**静默失效**，
扫描面在无人察觉的情况下缩小——下一次该文件真出现 N+1 时报的是「新增违规」，归因方向
完全错。与 scan_secrets 的 allowlist「只增不减」（F3-3）、audit_config 的 L4 白名单
（F3-5）是同一类腐烂，因此做成门禁而非文档条目。

本文件锁两件事
--------------
1. **真仓库锁**：随仓发布的白名单在真树上僵尸键为 0（这条在本仓修前是**红**的）；
2. **反证锁**：合成一个僵尸键（改名函数 / 越界行号 / 已删文件）必须被报出来且计入
   门禁总数、退出码非 0；同时有效键不得误判——否则任何人可以把门禁改成恒红或恒绿。

走子进程而不是 import：``check_n_plus_one.py`` 在 import 期包装 ``sys.stdout``
（io.TextIOWrapper），与 pytest 的输出捕获冲突，与 CI 的调用形态保持一致更可信。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "scripts" / "check_n_plus_one.py"
WHITELIST = ROOT / "scripts" / "allowed_n_plus_one.yaml"
# 一个确定不含「循环内 await 查询」的干净文件：用它隔离出「只有僵尸键」这一种失败
CLEAN_TARGET = "scripts/check_n_plus_one.py"


def _run(extra_args: list[str]) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--json", *extra_args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # 输出形态变了要立刻看见，不能当成"没违规"
        raise AssertionError(f"checker 输出不是 JSON：{exc}\nstdout={proc.stdout[:400]!r}") from exc
    return proc.returncode, payload


def test_shipped_whitelist_has_no_zombie_keys() -> None:
    """随仓发布的白名单每个键都必须仍然生效（修前：incremental.py 条目为僵尸键）。"""
    code, payload = _run([str(WHITELIST.parent.parent / "fastapi_app")])
    zombies = payload.get("zombie_whitelist_keys")
    assert isinstance(zombies, list), f"缺少 zombie_whitelist_keys 字段：{sorted(payload)}"
    assert zombies == [], f"白名单存在失效豁免键（静默缩扫描面）：{zombies}"
    assert code == 0, f"门禁退出码异常：code={code} violations={payload.get('violations')}"


@pytest.mark.parametrize(
    "zombie_key",
    [
        "fastapi_app/services/backup/this_module_was_deleted.py",
        f"{CLEAN_TARGET}::a_function_that_does_not_exist",
        f"{CLEAN_TARGET}:999999",
    ],
    ids=["deleted-file", "renamed-function", "line-out-of-range"],
)
def test_zombie_key_is_reported_and_blocks(zombie_key: str, tmp_path: Path) -> None:
    """三种失效形态都要被抓出来，且计入总数、退出码非 0（棘轮据此判 REGRESS）。"""
    wl = tmp_path / "wl.yaml"
    wl.write_text(f"# 合成白名单\n{zombie_key}\n", encoding="utf-8")
    code, payload = _run(["--whitelist", str(wl), CLEAN_TARGET])
    assert zombie_key in payload["zombie_whitelist_keys"], payload
    # 僵尸键不是 N+1 违规，但必须进总数——否则 quality_gate 的计数口径看不见它
    assert payload["violations"] == [], payload
    assert payload["total"] == 1, payload
    assert code == 1, f"僵尸键必须让门禁失败，实测 code={code}"


def test_valid_keys_are_not_flagged(tmp_path: Path) -> None:
    """反向防误杀：整文件 / 函数级 / 行级三种有效键各一条，均不得判为僵尸。"""
    valid = (
        "fastapi_app/services/backup/records.py\n"
        f"{CLEAN_TARGET}::find_zombie_keys\n"
        f"{CLEAN_TARGET}:10\n"
    )
    wl = tmp_path / "wl.yaml"
    wl.write_text(valid, encoding="utf-8")
    code, payload = _run(["--whitelist", str(wl), CLEAN_TARGET])
    assert payload["zombie_whitelist_keys"] == [], payload
    assert payload["total"] == 0, payload
    assert code == 0, f"有效键场景不该失败，实测 code={code} out={payload}"

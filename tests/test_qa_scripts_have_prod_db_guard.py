"""`tests/qa` 下「连库脚本必须先过生产库守卫」的回归锁（2026-11-17 OCR 复审）。

背景：`tests/qa/perf_final.py`、`_bench2.py` 在模块级就 `create_engine(settings.DATABASE_URL)`，
本机 `.env` 的 DATABASE_URL 就是**生产库**。2026-11-17 上线前审计 SUP-1 只加了
「禁止 import」守卫（`if __name__ != "__main__": raise`）——那个守卫拦的是被 import，
**直接运行**（`python tests/qa/perf_final.py`）时一行不差地照连生产库。

同目录 `_bench.py:12`、`performance_benchmark.py:17` 已有正确写法：
`require_non_production_database(settings.DATABASE_URL)`（2026-11-03 审查 S4），
非 `*_test` 库且未设 `PERF_TEST_ALLOW_PROD_DB=1` 就 `SystemExit`（fail-closed）。

两层验证：
1) 守卫函数本身的行为（生产库拦截、`*_test` 放行、显式允许放行、口令脱敏）；
2) 棘轮：`tests/qa/**` 里凡出现 `create_engine(settings.DATABASE_URL...)` 的脚本，
   必须在它**之前**调用 `require_non_production_database`——顺序也算断言，
   守卫挪到 create_engine 之后同样算回归（那时连接已于守卫前建好）。
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests._prod_guard import require_non_production_database

#: 自带等价守卫、不走库名判定的脚本：`data_generator_v3_db.py` 是**写入型**脚本，
#: 在 main() 里要求显式 `ERP_ALLOW_PROD_WRITE=1`（2026-10-03 第五轮审计，失败即 SystemExit）。
#: 它连库是在模块级，但守卫在入口函数里——语义是「写授权」而非「库名白名单」，
#: 故不并入本棘轮，也不能因为不在棘轮里就认为它没守卫。
LEGACY_SELF_GUARDED = {"tests/qa/data_generator_v3_db.py"}


# ---------------------------------------------------------------------------
# 1) 守卫函数行为
# ---------------------------------------------------------------------------
def test_production_database_blocked_by_default(monkeypatch):
    monkeypatch.delenv("PERF_TEST_ALLOW_PROD_DB", raising=False)
    with pytest.raises(SystemExit):
        require_non_production_database("postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system")


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test",
    "postgresql+psycopg://u:p@127.0.0.1:5432/erp_system_e2e_test",
])
def test_test_database_allowed(url, monkeypatch):
    monkeypatch.delenv("PERF_TEST_ALLOW_PROD_DB", raising=False)
    require_non_production_database(url)  # 不抛即通过


def test_explicit_allow_env(monkeypatch):
    monkeypatch.setenv("PERF_TEST_ALLOW_PROD_DB", "1")
    require_non_production_database("postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system")


def test_password_masked_in_message(monkeypatch):
    """生产库 DSN 的口令不得原样打进日志（本机就是生产机，报错会进终端/CI 日志）。"""
    monkeypatch.delenv("PERF_TEST_ALLOW_PROD_DB", raising=False)
    with pytest.raises(SystemExit) as exc:
        require_non_production_database(
            "postgresql+asyncpg://erp_app:S3cr3tPw@127.0.0.1:5432/erp_system"
        )
    assert "S3cr3tPw" not in str(exc.value)
    assert "***" in str(exc.value)


# ---------------------------------------------------------------------------
# 2) 棘轮：连生产库 URL 的脚本必须先调用守卫
# ---------------------------------------------------------------------------
def _qa_scripts_with_settings_database_url() -> list[Path]:
    hits = []
    for py in sorted((REPO / "tests" / "qa").rglob("*.py")):
        if "create_engine(settings.DATABASE_URL" in py.read_text(encoding="utf-8"):
            hits.append(py)
    return hits


def _guard_linenos(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "require_non_production_database"
    ]


def _engine_linenos(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "create_engine":
            continue
        uses_settings_url = any(
            isinstance(arg, ast.Attribute) and arg.attr == "DATABASE_URL"
            for arg in node.args
        )
        if uses_settings_url:
            out.append(node.lineno)
    return out


def test_every_engine_script_calls_guard_before_engine():
    scripts = _qa_scripts_with_settings_database_url()
    # 语义护栏：扫描面不能为空（空扫描 = 门禁形同虚设）
    assert len(scripts) >= 3, f"扫描面异常：仅发现 {len(scripts)} 个连生产库 URL 的脚本"

    offenders = []
    for path in scripts:
        rel = path.relative_to(REPO).as_posix()
        if rel in LEGACY_SELF_GUARDED:
            continue
        guards = _guard_linenos(path)
        engines = _engine_linenos(path)
        if not engines:
            offenders.append(f"{rel}: 文本命中但 AST 未解析出 create_engine(…DATABASE_URL…)")
            continue
        first_engine = min(engines)
        if not any(line < first_engine for line in guards):
            offenders.append(
                f"{rel}: 缺少 create_engine（第 {first_engine} 行）**之前**的 "
                f"require_non_production_database 调用（现有调用行号 {guards or '无'}）"
            )
    assert offenders == [], "以下脚本会连生产库但守卫缺失或位置不对：\n" + "\n".join(offenders)


def test_ratchet_covers_known_scripts():
    """已知的三个「直接运行即打生产库」脚本必须仍在扫描面内。

    覆盖不到就等于守卫漏面：脚本改名/搬走时这条会红，逼着回来改扫描口径。
    """
    found = {
        p.relative_to(REPO).as_posix()
        for p in _qa_scripts_with_settings_database_url()
    }
    assert {
        "tests/qa/perf_final.py",
        "tests/qa/_bench2.py",
        "tests/qa/_bench.py",
    } <= found

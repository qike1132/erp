"""压测/性能脚本的 fail-closed 守卫门禁（2026-10-17 审计 F-TEST-BE-TOP-02）。

两层验证：
1) _prod_guard.require_non_production 行为正确（回环拦截、显式允许放行、
   非回环不拦）；
2) 棘轮：tests/{stress,performance}/**.py 凡含 127.0.0.1:5002 / localhost:5002
   字面量且会发写请求的脚本，必须在 __main__ 块调用 require_non_production——
   「新增一个压测脚本忘了加守卫」被当场拦住。
"""
import ast
from pathlib import Path
from urllib.parse import urlparse

import pytest

REPO = Path(__file__).resolve().parents[2]
sys_path_added = False
if str(REPO) not in __import__('sys').path:
    import sys
    sys.path.insert(0, str(REPO))

from tests._prod_guard import require_non_production  # noqa: E402

# stress_test.py 有自己的守卫实现（先于本模块存在），不强制迁移
LEGACY_SELF_GUARDED = {"tests/stress/stress_test.py"}


# ---------------------------------------------------------------------------
# 1) 守卫函数行为
# ---------------------------------------------------------------------------
def test_loopback_blocked_by_default(monkeypatch):
    monkeypatch.delenv('STRESS_TEST_ALLOW_PROD', raising=False)
    with pytest.raises(SystemExit):
        require_non_production('http://127.0.0.1:5002')


@pytest.mark.parametrize('url', [
    'http://localhost:5002', 'http://0.0.0.0:5002', 'http://::1:5002',
    'http://192.168.0.95:5002',
], ids=['localhost', 'all-zero', 'ipv6', 'lan'])
def test_non_loopback_or_allowed_passes(url, monkeypatch):
    # 非回环地址不拦；回环地址显式允许后放行
    monkeypatch.delenv('STRESS_TEST_ALLOW_PROD', raising=False)
    host = (urlparse(url).hostname or '').lower()
    if host in {'127.0.0.1', 'localhost', '0.0.0.0', '::1', ''}:
        monkeypatch.setenv('STRESS_TEST_ALLOW_PROD', '1')
    require_non_production(url)  # 不抛即通过


def test_explicit_allow_env(monkeypatch):
    monkeypatch.setenv('STRESS_TEST_ALLOW_PROD', '1')
    require_non_production('http://127.0.0.1:5002')


# ---------------------------------------------------------------------------
# 2) 棘轮：所有指向生产回环口的写脚本必须调用守卫
# ---------------------------------------------------------------------------
def _scripts_with_prod_base_url() -> list[Path]:
    roots = [REPO / 'tests' / 'stress', REPO / 'tests' / 'performance']
    hits: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for py in root.rglob('*.py'):
            src = py.read_text(encoding='utf-8')
            if '127.0.0.1:5002' in src or 'localhost:5002' in src:
                hits.append(py)
    return sorted(hits)


def _has_guard_call(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and ast.unparse(node.test).startswith('__name__'):
            for stmt in ast.walk(node):
                if (isinstance(stmt, ast.Call) and isinstance(stmt.func, ast.Name)
                        and stmt.func.id == 'require_non_production'):
                    return True
    return False


def test_every_prod_url_script_calls_guard():
    scripts = _scripts_with_prod_base_url()
    # 语义护栏：扫描面不能为空（空扫描 = 门禁形同虚设）
    assert len(scripts) >= 10, f'扫描面异常：仅发现 {len(scripts)} 个脚本'
    missing = [
        p.relative_to(REPO).as_posix() for p in scripts
        if p.relative_to(REPO).as_posix() not in LEGACY_SELF_GUARDED and not _has_guard_call(p)
    ]
    assert missing == [], (
        f'以下脚本硬编码生产回环口但缺少 require_non_production 守卫：{missing}'
    )

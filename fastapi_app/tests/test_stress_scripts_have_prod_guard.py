"""压测/性能脚本的 fail-closed 守卫门禁（2026-10-17 审计 F-TEST-BE-TOP-02）。

两层验证：
1) _prod_guard.require_non_production 行为正确（回环拦截、显式允许放行、
   非回环不拦）；
2) 棘轮：tests/{stress,performance}/**.py 凡含 127.0.0.1:5002 / localhost:5002
   字面量且会发写请求的脚本，必须在 __main__ 块调用 require_non_production——
   「新增一个压测脚本忘了加守卫」被当场拦住。
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys_path_added = False
if str(REPO) not in __import__('sys').path:
    import sys
    sys.path.insert(0, str(REPO))

from tests._prod_guard import require_non_production

# stress_test.py 有自己的守卫实现（先于本模块存在），不强制迁移
LEGACY_SELF_GUARDED = {"tests/stress/stress_test.py"}


# ---------------------------------------------------------------------------
# 1) 守卫函数行为
# ---------------------------------------------------------------------------
def test_loopback_blocked_by_default(monkeypatch):
    monkeypatch.delenv('STRESS_TEST_ALLOW_PROD', raising=False)
    with pytest.raises(SystemExit):
        require_non_production('http://127.0.0.1:5002')


@pytest.mark.parametrize('url', ['http://localhost:5002', 'http://0.0.0.0:5002'],
                         ids=['localhost', 'all-zero'])
def test_loopback_or_unspecified_passes_with_explicit_allow(url, monkeypatch):
    """回环/未指定地址在显式允许后放行（默认拦由 test_loopback_blocked_by_default 看住）。"""
    monkeypatch.setenv('STRESS_TEST_ALLOW_PROD', '1')
    require_non_production(url)


def test_lan_address_passes_without_any_override(monkeypatch):
    """非回环地址**不需要**任何 override 就该放行。

    评审（2026-11-19）：原来 'lan' 与回环地址共用同一参数化，而那个用例无条件
    setenv('STRESS_TEST_ALLOW_PROD','1') —— 环境变量一置 1 就什么都不拦，于是
    「非回环不拦」这条行为彻底失去判定力（把 _is_blocked_host 改成恒 True 也不会红）。
    """
    monkeypatch.delenv('STRESS_TEST_ALLOW_PROD', raising=False)
    require_non_production('http://192.168.0.95:5002')


@pytest.mark.parametrize('url', ['http://[::1]:5002', 'http://[0:0:0:0:0:0:0:1]:5002'],
                         ids=['ipv6-short', 'ipv6-long'])
def test_ipv6_loopback_blocked_by_default(url, monkeypatch):
    """`::1` 也是回环，默认必须拦。

    2.3（2026-10-17 审计 P2）：原参数化用例传的是**无方括号**的 `http://::1:5002`，
    `urlparse(...).hostname` 解析不出 `::1`（得到 ''），于是走了「显式允许 → 不抛」的
    分支 —— `require_non_production` 退化成 no-op 也照绿。改用标准写法并断言默认被拦
    （守卫的 `_LOOPBACK_HOSTS` 本来就含 '::1'，此前只是没被真正测到）。
    """
    monkeypatch.delenv('STRESS_TEST_ALLOW_PROD', raising=False)
    with pytest.raises(SystemExit):
        require_non_production(url)


@pytest.mark.parametrize('url', [
    'http://[::ffff:127.0.0.1]:5002',   # IPv4-mapped：ipaddress.is_loopback 为 False
    'http://127.1:5002',                # 省略写法：ipaddress 不接受，系统解析器认
    'http://localhost.:5002',           # FQDN 尾点
], ids=['ipv4-mapped', 'short-form', 'fqdn-dot'])
def test_loopback_equivalents_blocked_by_default(url, monkeypatch):
    """回环的等价写法也必须默认拦（评审 2026-11-19：`::ffff:127.0.0.1` 当时能过）。

    `_is_blocked_host` 只靠 `is_loopback`/`is_unspecified` 时，IPv4-mapped 形式
    （`::ffff:127.0.0.1`）的 `is_loopback` 是 False，于是被当成「专门的压测环境」放行 ——
    而它指向的正是本机生产 uvicorn。
    """
    monkeypatch.delenv('STRESS_TEST_ALLOW_PROD', raising=False)
    with pytest.raises(SystemExit):
        require_non_production(url)


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


def test_stress_dir_contributes_no_pytest_cases():
    """`tests/stress` 是压测脚本目录（0 个 pytest 用例），CI 因此 `--ignore` 它。

    两边必须同口径，本用例把「目录里没有用例」与「CI 忽略它」绑在一起：
    * 有人往这里加 pytest 用例 → 它不会被 CI 执行（ignore 就在那一行），本断言红；
    * 有人删掉 CI 的 `--ignore=tests/stress` → 这些脚本会在收集期被 import，而其中
      若干在没有 `__main__` 守卫的年代会真的发请求（见 test_auth.py docstring 记录的
      2026-10-03 事故：每次跑 pytest 都打 10 次真实登录），本断言同样红。

    口径说明（2026-11-18 评审）：`tests/stress/test_auth.py` 的**文件名**匹配
    `test_*.py`，所以「0 用例」指的是它内部没有 `def test_`（它是脚本，靠
    `python tests/stress/test_auth.py` 手工跑），不是「pytest 看不见这个文件」。
    """
    stress = REPO / 'tests' / 'stress'
    offenders = sorted(
        p.relative_to(stress).as_posix() for p in stress.rglob('*.py')
        if re.search(r'^\s*(async )?def test_', p.read_text(encoding='utf-8'), re.MULTILINE)
    )
    assert offenders == [], f'tests/stress 只放压测脚本，不得出现 pytest 用例：{offenders}'

    # 读 CI 时先去掉整行注释：本批的注释里正在讨论这条 ignore，若只做整文件子串
    # 匹配，把 flag 删掉但注释留着也会判定通过（与 test_gate_selftest_wired 同口径）。
    ci = (REPO / '.github' / 'workflows' / 'ci-cd.yml').read_text(encoding='utf-8')
    ci_code = '\n'.join(
        line for line in ci.splitlines() if not line.lstrip().startswith('#')
    )
    assert '--ignore=tests/stress' in ci_code, (
        'tests/stress 无用例却仍在 pytest 收集范围内：删掉 ignore 前必须先把这些脚本'
        '改成收集期无副作用，否则收集就会发真实请求'
    )

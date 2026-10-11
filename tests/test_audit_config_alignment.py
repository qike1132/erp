"""审计配置对齐的回归护栏（评审 2026-10-11 的一批修复）。

1. L11 的 ``_REQUIRED_ENV_VARS`` 曾含 ``DATABASE_URL``（应用侧只是可选覆盖）与
   ``ENVIRONMENT``（全仓 0 读取），稳定产出 2 条 MEDIUM 误报。本测试锁死「表里
   每一项都在 ``.env.example`` 里真实存在」，防止再次漂移。
2. ``utils.redis_cache`` 的默认 host 曾是 ``localhost`` —— Windows 上解析优先
   ``::1``，而 redis 只 bind IPv4，漏配环境变量时连不上。
"""
import ast
import inspect
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_L11 = _REPO_ROOT / "scripts" / "prod_audit" / "layers" / "l11_deployment.py"
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"
_REDIS_CACHE = _REPO_ROOT / "utils" / "redis_cache.py"


def _required_env_vars() -> list[str]:
    tree = ast.parse(_L11.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        target = value = None
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        if isinstance(target, ast.Name) and target.id == "_REQUIRED_ENV_VARS" and value is not None:
            return [elt.value for elt in value.elts]
    raise AssertionError("l11_deployment.py 未找到 _REQUIRED_ENV_VARS")


def _env_example_keys() -> set[str]:
    keys = set()
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def test_l11_required_env_vars_are_declared_in_env_example():
    """L11 要求的每个环境变量都必须在 .env.example 里声明（否则是误报）。"""
    declared = _env_example_keys()
    missing = [v for v in _required_env_vars() if v not in declared]
    assert not missing, (
        f"_REQUIRED_ENV_VARS 含 .env.example 未声明的变量（会产出误报）：{missing}"
    )


def test_redis_cache_default_host_is_ipv4_loopback():
    """utils.redis_cache 的默认 host 必须是 127.0.0.1，不得是 localhost。"""
    from utils.redis_cache import RedisCacheManager

    default = inspect.signature(RedisCacheManager.init_app).parameters["redis_host"].default
    assert default == "127.0.0.1", f"init_app 的 redis_host 默认值应为 127.0.0.1，实为 {default!r}"
    src = _REDIS_CACHE.read_text(encoding="utf-8")
    assert "os.getenv('REDIS_HOST', 'localhost')" not in src, "app.config 回退分支仍用 localhost"

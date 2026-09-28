"""A 止血改动的静态回归锁:停止范围(含 Redis)、受管集合、端口判据、环境变量写入。

无 GUI 测试基建,沿用本仓既有做法以文本断言锁定(见 test_server_manager_erp_web.py)。
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "server_manager.py"
TEXT = SRC.read_text(encoding="utf-8")


# ── 受管服务全集 ───────────────────────────────────────────────────────────
def test_svc_all_constant_covers_five_services() -> None:
    """受管全集必须含两个 Redis 服务——否则「全部停止」名不副实(评审确认项)。"""
    m = re.search(r"^_SVC_ALL = \((.+)\)$", TEXT, re.M)
    assert m, "缺少 _SVC_ALL 常量"
    members = m.group(1)
    for name in ("_SVC_API", "_SVC_ARQ", "_SVC_WEB", "_SVC_REDIS_CACHE", "_SVC_REDIS_BROKER"):
        assert name in members, f"_SVC_ALL 缺 {name}"


def test_stop_paths_use_svc_all() -> None:
    """停止/重启/受管 PID 排除三条路径都必须按 _SVC_ALL 迭代。"""
    for fn in ("_managed_service_pids", "_stop_managed_services", "_service_cmd_sync"):
        body = TEXT[TEXT.index(f"def {fn}") :][:1400]
        assert "for name in _SVC_ALL" in body, f"{fn} 未按 _SVC_ALL 迭代"


def test_start_path_keeps_dedicated_redis_helpers() -> None:
    """启动流程不得改用 _SVC_ALL:Redis 由专属助手先起,复用会重复启动。"""
    body = TEXT[TEXT.index("def _start_services_flow") :][:1600]
    assert "for name in _SVC_ALL" not in body
    assert "_start_redis()" in body


def test_ensure_production_stopped_does_not_stop_redis() -> None:
    """切开发模式前的「停生产」不得停 Redis——开发模式同样依赖它。"""
    body = TEXT[TEXT.index("def _ensure_production_stopped") :][:1200]
    assert "for name in _SVC_ALL" not in body


# ── 端口判据 ───────────────────────────────────────────────────────────────
def test_managed_pid_set_excluded_from_port_cleanup() -> None:
    """_release_ports 必须传受管 PID 排除集,否则「启动服务」会强杀在跑的生产进程。"""
    body = TEXT[TEXT.index("def _release_ports") :][:600]
    assert "exclude=" in body and "_managed_service_pids()" in body


def test_substring_port_killer_is_gone() -> None:
    """子串匹配端口的 _kill_port_process(':5002' 命中 ':50021')必须删除,只留精确版。"""
    assert "def _kill_port_process" not in TEXT
    assert "def _get_port_occupier" not in TEXT


def test_stop_redis_never_kills_by_port() -> None:
    """_stop_redis 不得再按端口盲杀——那会 taskkill 掉 NSSM 受管的 erp-redis。"""
    body = TEXT[TEXT.index("def _stop_redis") :][:1200]
    assert "_kill_port_process" not in body


# ── 环境变量写入 ───────────────────────────────────────────────────────────
def test_env_extra_written_as_multiple_argv_elements() -> None:
    """AppEnvironmentExtra 必须逐元素传参:NSSM 只按第一个 '=' 切分单个元素,
    拼成一串会让 6 个变量里只剩 1 个(且值畸变),而界面仍报「已注册」。"""
    body = TEXT[TEXT.index("def _nssm_install") : TEXT.index("def _apply_depends")]
    assert "AppEnvironmentExtra" in body
    # 值以列表传入、写入时按元素展开
    assert "isinstance(val, list)" in body, "未按列表值逐元素展开"
    assert "[nssm, 'set', name, key]" in body, "未见按 key 组装 argv 的写法"
    # 调用点须构造列表而非空格拼接的整串
    flow = TEXT[TEXT.index("def _install_services_flow") :][:900]
    assert "env_extra = [" in flow, "env_extra 应以列表构造"
    assert "' '.join" not in flow, "env_extra 不应再用空格拼成单串"

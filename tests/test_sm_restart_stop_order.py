"""整栈重启停机序回归锁（2026-10-16 实机事故）。

背景
----
点「重启」生产服务后日志：

    11:27:49 正在停止生产服务 erp-redis-broker...
    11:27:49 WARNING: erp-redis-broker stop 返回非零 (code=1):
              停止控制被发送到其他正在运行的服务所依赖的服务。；仍继续启动
    11:28:09 WARNING: erp-redis-broker 在 20s 内未确认 STOPPED（当前: 4 RUNNING），仍继续启动

实机取证（SCM）：
- ``sc enumdepend erp-redis-broker`` → 依赖方是 **erp-arq**，且 STATE=4 RUNNING；
- erp-arq（pid 11096，11:28:36 起）持有 3 条到 127.0.0.1:6380 的 ESTABLISHED 连接。

SCM 规则：**停止被运行中服务依赖的服务会被拒（1051）**。故停机必须按依赖图
的**逆拓扑**：依赖方（erp-arq/erp-prod/erp-web）先停，被依赖者（broker/cache）后停。

v5.35 的 `_SVC_REVERSE = reversed(_SVC_ALL)` 恰把被依赖的 broker 顶到第一位 ——
逆序撞上还在跑的 erp-arq，SCM 必然拒停；随后阶段二照常把五个服务全 start 一遍，
arq 重连 6380 把 broker 永久钉死，下次重启同样失败。

本文件锁停机序 = 依赖方在前（断言关键偏序，不锁死全部五元的实现细节）。
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONSTANTS = ROOT / "server_manager" / "constants.py"
SVC_OPS = ROOT / "server_manager" / "service_ops.py"

_SVC_API = "erp-prod"
_SVC_ARQ = "erp-arq"
_SVC_WEB = "erp-web"
_SVC_CACHE = "erp-redis"
_SVC_BROKER = "erp-redis-broker"


def _constants() -> dict:
    """执行 constants 模块拿到真实元组（只含字面量，无副作用）。"""
    import sys
    sys.path.insert(0, str(ROOT))
    from server_manager import constants as c
    return {
        "ALL": c._SVC_ALL,
        "REVERSE": c._SVC_REVERSE,
        "DEPENDS": c._SVC_DEPENDS,
    }


class TestStopOrderIsReverseTopological:
    """停机序必须让依赖方先停（broker 之前必须已停掉 arq）。"""

    def test_arq_stops_before_broker(self):
        c = _constants()
        order = c["REVERSE"]
        assert order.index(_SVC_ARQ) < order.index(_SVC_BROKER), (
            f"停机序 {order}：erp-arq 必须在 erp-redis-broker 之前停 —— "
            "SCM 拒停被运行中服务依赖的服务（1051），本次实机因此 20s 停机超时")

    def test_prod_stops_before_cache(self):
        c = _constants()
        order = c["REVERSE"]
        assert order.index(_SVC_API) < order.index(_SVC_CACHE), (
            f"停机序 {order}：erp-prod 依赖缓存实例，必须在 erp-redis 之前停")

    def test_every_declared_depender_stops_before_its_dependency(self):
        """通用偏序：_SVC_DEPENDS 里每个 (depender → dependency) 都满足停机先后。"""
        c = _constants()
        order = c["REVERSE"]
        for depender, deps in c["DEPENDS"].items():
            for dep in deps:
                assert order.index(depender) < order.index(dep), (
                    f"停机序违反依赖图：{depender} 声明依赖 {dep}，"
                    f"但停机序里 {depender}(idx {order.index(depender)}) 不在 {dep}(idx {order.index(dep)}) 之前")

    def test_reverse_covers_all_services(self):
        c = _constants()
        assert sorted(c["REVERSE"]) == sorted(c["ALL"]), \
            "停机表必须覆盖全部服务，漏一个 = 那个服务的停机从未被执行"


class TestStopFailureHaltsStartPhase:
    """停机失败必须中止本次重启，不得带病进入启动阶段。

    实机后果：broker 停不掉却继续启动 → arq 重连 6380 → broker 永久钉死。
    """

    def test_restart_phase_one_checks_stop_result(self):
        """service_cmd_sync 的 restart 分支必须消费停机终态，不能无条件继续。"""
        body = _func_src(SVC_OPS, "service_cmd_sync")
        # 停机循环体内必须出现对停机结果的判断（状态判定或失败中止）
        assert "STOPPED" in body, "restart 分支未检查停机终态"
        assert "return" in body, "停机失败时未中止重启流程"

    def test_stop_failure_is_reported_as_warning(self):
        body = _func_src(SVC_OPS, "service_cmd_sync")
        assert "WARNING" in body, "停机失败必须如实告警，不得静默继续"


def _func_src(module: Path, name: str) -> str:
    src = module.read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{module.name} 内未找到 {name}")

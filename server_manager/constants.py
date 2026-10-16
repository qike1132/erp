"""server_manager 包的字面常量层。

只放不依赖本包其它模块的字面常量;凡在导入期由函数计算得出的值
(_PROJECT_DIR / _FRONTEND_DIR / _PYTHON_EXE)与其 provider 函数留在
server_manager.app,以避免 constants ← app 的循环导入。
"""
import sys
import urllib.request
from pathlib import Path

_IS_WINDOWS = sys.platform == 'win32'

_VERSION = 'v5.40'
_WINDOW_TITLE = f'ERP 服务器管理器 {_VERSION}'
_REDIS_PORT = 6379
_REDIS_EXE_PATHS = [Path(r'C:\Redis\redis-server.exe'), Path(r'C:\Program Files\Redis\redis-server.exe')]
_REDIS_CONF_PATHS = [Path(r'C:\Redis\redis.windows.conf'), Path(r'C:\Redis\redis.conf')]
# 生产模式：Windows 服务 (NSSM) 名称与 NSSM 常见安装位置
_SVC_API = 'erp-prod'
_SVC_ARQ = 'erp-arq'
# nginx 静态服务:prod_runner 已不再托管前端,由独立 NSSM 服务 erp-web 直管 nginx.exe。
# 无依赖(反代上游未起只 502,静态照常服务);与 erp-prod 启停解耦。
_SVC_WEB = 'erp-web'
# Redis 服务：缓存 6379 与 ARQ broker 6380 各一个实例。
#   ★ erp-arq 必须依赖 _SVC_REDIS_BROKER：没有 DependOnService 时，开机由 SCM
#     并行启动，erp-arq 会抢在 broker 之前连 6380 → 超时退出 → NSSM 5s 后重拉，
#     形成无限重启循环，cron/备份/报表全部静默不执行（2026-09-16 实测现场）。
_SVC_REDIS_CACHE = 'erp-redis'
_SVC_REDIS_BROKER = 'erp-redis-broker'
# erp-prod 依赖缓存实例（Redis 不可用时后端缓存层大面积降级）
_SVC_DEPENDS = {
    _SVC_API: [_SVC_REDIS_CACHE],
    _SVC_ARQ: [_SVC_REDIS_BROKER],
}
# 受管服务全集：停止 / 重启 / 受管 PID 排除都按它迭代。
#   ★ 含两个 Redis 实例：用户决策「停止 = 连 Redis 一起停」；且受管 PID 排除集
#     必须完整，否则端口清理会误杀正在服务的受管进程（NSSM 5 秒后又拉起）。
#   ★ 启动流程【不】用它：Redis 由 _start_redis / _ensure_redis_broker 先起。
#   ★ 切开发模式的「停生产」也不用它：开发模式同样依赖 Redis。
_SVC_ALL = (_SVC_API, _SVC_ARQ, _SVC_WEB, _SVC_REDIS_CACHE, _SVC_REDIS_BROKER)
# 整栈重启的**停机**顺序必须按依赖图**逆拓扑**：依赖方（erp-prod/erp-arq/erp-web）
#   先停，被依赖者（erp-redis/erp-redis-broker）后停。
#   ★ 为什么不是 reversed(_SVC_ALL)（2026-10-16 实机事故）：字面逆序把被依赖的
#     broker 顶到第一位，此时 erp-arq 还在 RUNNING 并持有到 6380 的连接，SCM 以
#     「停止控制被发送到其他正在运行的服务所依赖的服务」（1051）拒停 broker →
#     停机阶段全部空转超时（20s/个）→ 阶段二照常启动 → arq 重连 6380 把 broker
#     永久钉死 → 下次重启同样失败。实机取证：sc enumdepend erp-redis-broker 的唯一
#     依赖方是 erp-arq 且 RUNNING；pid 11096 持有 3 条到 127.0.0.1:6380 的
#     ESTABLISHED。故停机序由 _SVC_DEPENDS 推导（被依赖者越晚停越安全）。
#   启动仍按 _SVC_ALL 原序（被依赖者先起，与 SCM 开机序一致）。
def _stop_order():
    """按 _SVC_DEPENDS 拓扑排序生成停机序：依赖方在前，被依赖者在后。

    _SVC_DEPENDS 是 depender -> [dependencies]（erp-arq 依赖 broker）。停机时依赖方
    必须先停，故做一次逆拓扑 DFS：访问某服务前，先把**依赖它的**服务入列。
    """
    deps: dict[str, set[str]] = {name: set() for name in _SVC_ALL}
    for depender, targets in _SVC_DEPENDS.items():
        for target in targets:
            deps.setdefault(target, set())   # target 可能暂无依赖方
            if depender in deps:
                deps[target].add(depender)

    order: list[str] = []

    def _visit(svc: str) -> None:
        if svc in order:
            return
        for depender in sorted(deps.get(svc, ()), key=_SVC_ALL.index):
            _visit(depender)               # 依赖方先入列
        order.append(svc)

    for svc in _SVC_ALL:
        _visit(svc)
    return tuple(order)


_SVC_REVERSE = _stop_order()
# 会写入 UVICORN_WORKERS 的服务：erp-prod 是唯一消费方；erp-arq 不读它，一并写入
#   只为保持两者 AppEnvironmentExtra 一致（免得「安装生产服务」拿其中一个的值覆盖出分歧）。
#   ★ 刻意不含 _SVC_WEB：erp-web 是 nginx，Python 环境变量对它无意义 ——
#     安装流程给它的 env 列表本就是空的。别为「统一」把它并进来。
_SVC_UVICORN_WORKERS = (_SVC_API, _SVC_ARQ)
# ARQ broker 端口（与 config/redis-broker.conf 的 port 一致）
_REDIS_BROKER_PORT = 6380
_NSSM_CANDIDATES = [
    Path(r'C:\nssm\nssm.exe'),
    Path(r'C:\Program Files\nssm\nssm.exe'),
    Path(r'C:\Program Files (x86)\nssm\nssm.exe'),
    Path(r'C:\tools\nssm\nssm.exe'),
]
_PROD_STATUS_FILE = Path(r'logs\prod_runner.json')

_API_PORT = 5002
_WEB_PORT = 3000

# 本机探针必须绕开系统代理：prod_runner 曾因代理转发 127.0.0.1 探测导致间歇失败、
# 进而误判后端崩溃并重启（见 prod_runner 内 _OPENER_DIRECT 注释）。
_HTTP_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

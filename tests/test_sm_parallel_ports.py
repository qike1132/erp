"""server_manager v5.45 并行改造回归锁（2026-11-02）。

背景
----
v5.40 及之前：开发模式与生产模式**互斥**——启动开发先停生产
（dev_mode.start_dual_worker → ensure_production_stopped），启动生产先停开发
（app._start_services_flow → ensure_development_stopped），且开发栈直接复用
生产端口 5002/3000。用户要求：两栈可**同时运行**，调试（开发）模式改用
独立端口。

v5.45 改造：
1. 开发栈迁独立端口 _DEV_API_PORT(5102) / _DEV_WEB_PORT(5173)；
2. 双向解除互斥：开发启动只清开发端口（不动生产），生产启动不再停开发；
3. Redis 是共享基础设施：生产在跑（或状态不可知）时，停开发/重启开发/
   管理器退出都**保留** Redis；
4. vite dev 代理经 BACKEND_INTERNAL_URL 注入指向调试后端（默认回落 5002）。

本文件锁以上四条，防止回退到互斥/抢端口形态。

运行: python -m pytest tests/test_sm_parallel_ports.py -q
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "server_manager"
DM = PKG / "dev_mode.py"
APP = PKG / "app.py"
CONST = PKG / "constants.py"
VITE_TS = ROOT / "frontend-vite" / "vite.config.ts"
VITE_JS = ROOT / "frontend-vite" / "vite.config.js"  # vue-tsc -b 生成物（git 忽略）

sys.path.insert(0, str(ROOT))

import pytest

from server_manager.constants import (
    _API_PORT,
    _DEV_API_PORT,
    _DEV_WEB_PORT,
    _WEB_PORT,
)


def _func_src(path: Path, name: str) -> str:
    """按 AST 取目标模块内某函数/方法的源码段（含缩进），不依赖文本顺序。"""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{path.name} 内未找到 {name}")


def _mentions_prod_port(body: str) -> bool:
    """body 是否引用**生产**端口常量（_API_PORT/_WEB_PORT）。

    必须用词边界：'_API_PORT' 是 '_DEV_API_PORT' 的子串，裸 `in` 会误报。
    '_' 属于 \\w，故 \\b_API_PORT\\b 不会命中 _DEV_API_PORT 内部。
    """
    return bool(re.search(r"\b_API_PORT\b", body) or re.search(r"\b_WEB_PORT\b", body))


# ── 1. 常量：端口隔离 ──────────────────────────────────────────────────────

def test_dev_ports_differ_from_prod_ports() -> None:
    """开发端口必须与生产端口隔离——同端口 = 双后端抢监听 = 并行改造失效。"""
    assert _DEV_API_PORT != _API_PORT, "开发后端不得复用生产 5002"
    assert _DEV_WEB_PORT != _WEB_PORT, "开发前端不得复用生产 3000"


def test_dev_ports_are_5102_and_5173() -> None:
    """锁定选型（vite.config.ts 的 CSP、管理器药丸、文档均按此写死）。"""
    assert (_DEV_API_PORT, _DEV_WEB_PORT) == (5102, 5173)


# ── 2. 开发启动：不再停生产，只清开发端口 ─────────────────────────────────

def test_dev_start_does_not_stop_production() -> None:
    """并行契约核心①：开发启动流程不得再调用 ensure_production_stopped。"""
    worker = _func_src(DM, "start_dual_worker")
    assert "ensure_production_stopped" not in worker, (
        "开发启动不得停生产（v5.45 并行契约）；历史互斥行为已废弃")
    # 清理动作必须是开发专用端口原语
    assert "_release_dev_ports" in worker, "开发启动未走 _release_dev_ports"


def test_dev_port_release_fails_fast() -> None:
    """_release_dev_ports 必须消费 kill_port_sync 返回值：still_occupied 时中止。"""
    body = _func_src(DM, "_release_dev_ports")
    assert "still_occupied" in body, "未消费 'still_occupied'（端口没清干净会假成功）"
    assert _func_src(DM, "_release_dev_ports").count("kill_port_sync") >= 2, "两个开发端口都要清"


def test_dev_thread_uses_dev_ports_only() -> None:
    """并行契约核心②：uvicorn/vite/探测全部走开发端口，绝不动生产端口。"""
    body = _func_src(DM, "start_dual_thread")
    assert "str(_DEV_API_PORT)" in body, "后端未绑 _DEV_API_PORT"
    assert "str(_DEV_WEB_PORT)" in body, "vite 未用 _DEV_WEB_PORT"
    assert "http://127.0.0.1:{_DEV_API_PORT}/api/health" in body, "后端探测未指向开发端口"
    assert "http://127.0.0.1:{_DEV_WEB_PORT}/" in body, "前端探测未指向开发端口"
    assert "BACKEND_INTERNAL_URL': f'http://127.0.0.1:{_DEV_API_PORT}'" in body, (
        "vite 代理未注入开发后端地址")
    assert not _mentions_prod_port(body), "启动线程不得引用生产端口常量"


def test_dev_backend_binds_loopback() -> None:
    """AGENTS.md 红线 #3：开发后端同样只绑 127.0.0.1，不得 0.0.0.0。"""
    body = _func_src(DM, "start_dual_thread")
    assert "'--host', '127.0.0.1'" in body


# ── 3. 生产启动：不再停开发 ───────────────────────────────────────────────

def test_prod_start_does_not_stop_development() -> None:
    """并行契约核心③：生产启动流程不得再调用（已删除的）停开发原语。"""
    body = _func_src(APP, "_start_services_flow")
    assert "ensure_development_stopped" not in body, (
        "生产启动不得停开发（v5.45 并行契约）——两栈端口隔离可同时运行")


def test_ensure_development_stopped_removed() -> None:
    """死代码不回潮：生产启动解耦后，该原语零调用点，已删除。"""
    dm_src = DM.read_text(encoding="utf-8")
    app_src = APP.read_text(encoding="utf-8")
    assert "def ensure_development_stopped" not in dm_src, "dev_mode 不应再定义该死方法"
    assert "_ensure_development_stopped" not in app_src, "app 不应再保留死转发"


# ── 4. 停止/重启/紧急停止：范围语义 ───────────────────────────────────────

def test_dev_stop_releases_dev_ports_not_prod() -> None:
    """停开发只清开发端口（生产 5002/3000 上的受管进程一概不碰）。"""
    body = _func_src(DM, "stop_dual_flow")
    assert "kill_port_sync(_DEV_API_PORT)" in body
    assert "kill_port_sync(_DEV_WEB_PORT)" in body
    assert not _mentions_prod_port(body), "停开发不得清理生产端口"


def test_dev_stop_keeps_shared_redis_when_prod_runs() -> None:
    """并行契约核心④：Redis 共享——生产在跑时停开发必须保留 Redis。"""
    body = _func_src(DM, "stop_dual_flow")
    assert "_production_may_run()" in body, "停开发未判生产运行态（共享 Redis 会被拔掉）"
    restart = _func_src(DM, "restart_dual_thread")
    assert "_production_may_run()" in restart, "重启开发未判生产运行态"


def test_production_may_run_tristate() -> None:
    """行为级：三态语义——RUNNING/未知 → 保留（fail-safe）；STOPPED/未安装 → 可停。"""
    from server_manager.dev_mode import DevModeOps

    def _ops_with_state(state: str) -> DevModeOps:
        class _Svc:
            def svc_state(self, _name):
                return state

        class _Q:
            def put(self, *_a):
                return None

        class _Gate:
            def checkpoint(self):
                return None

        return DevModeOps(_Q(), _Gate(), ROOT, _Svc(), object(),
                          python_exe="x", frontend_dir=ROOT)

    assert _ops_with_state("4  RUNNING")._production_may_run() is True
    assert _ops_with_state("未知")._production_may_run() is True, (
        "查不出来 ≠ 没在跑：未知必须按可能在跑处理（fail-safe）")
    assert _ops_with_state("1  STOPPED")._production_may_run() is False
    assert _ops_with_state("未安装")._production_may_run() is False


def test_stop_all_covers_dev_ports() -> None:
    """紧急停止 = 全停：端口清扫清单必须含两个开发端口（残留兜底）。"""
    body = _func_src(APP, "stop_all")
    assert "_DEV_API_PORT" in body and "_DEV_WEB_PORT" in body, (
        "紧急停止未覆盖开发端口——开发栈残留进程不会被清扫")


def test_quit_keeps_shared_redis_when_prod_runs() -> None:
    """管理器退出与停开发同口径：生产在跑时不收共享 Redis。"""
    body = _func_src(APP, "_do_quit")
    assert "_production_may_run()" in body, "退出未判生产运行态"


# ── 5. vite 代理：BACKEND_INTERNAL_URL 注入 ───────────────────────────────

def test_vite_ts_proxy_reads_env() -> None:
    """vite.config.ts 的 dev 代理必须读 BACKEND_INTERNAL_URL（默认 5002）。"""
    src = VITE_TS.read_text(encoding="utf-8")
    assert "BACKEND_INTERNAL_URL" in src, "dev 代理未接 BACKEND_INTERNAL_URL"
    assert "process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:5002'" in src, (
        "缺省必须回落生产后端 5002（手工 npm run dev 的既有行为）")


def test_vite_ts_preview_keeps_prod_backend() -> None:
    """preview 面向生产构建，代理恒定指向 5002，不随调试变量漂移。"""
    src = VITE_TS.read_text(encoding="utf-8")
    start = src.index("preview: {")
    seg = src[start : src.index("optimizeDeps:", start)]  # preview 块止于其后首个顶层键
    assert "http://127.0.0.1:5002" in seg, "preview 代理必须指向生产后端"
    assert "backendInternal" not in seg, "preview 代理不得使用 dev 的环境变量"


@pytest.mark.skipif(not VITE_JS.exists(),
                    reason="CI 干净检出无 vue-tsc 生成物 vite.config.js（.gitignore 忽略）")
def test_vite_js_matches_ts_on_env_proxy() -> None:
    """本地 vite.config.js（Vite 实际加载者）与 .ts 同源：env 代理一致。"""
    src = VITE_JS.read_text(encoding="utf-8")
    assert "process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:5002'" in src, (
        "生成物 vite.config.js 未包含 env 代理——Vite 优先加载 .js，"
        "改了 .ts 忘跑 vue-tsc -b 会让代理仍指向旧地址")

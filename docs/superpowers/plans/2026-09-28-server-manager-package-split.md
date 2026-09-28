# server_manager 完整包化 + 门禁收严 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 3082 行的单文件 `server_manager.py` 重组为 `server_manager/` 包(四个无 Tk 依赖的操作模块 + widgets/action_gate/constants + `app.py`),并把仓库自带规模/函数长度门禁的扫描范围纳入仓库根。

**Architecture:** 操作层按职责分域(服务/进程端口/Redis/开发模式),各模块**不 import Tk、不 import app**,通过构造注入接收 `msg_queue` 与 `gate` 回调,并**自己持有**其进程状态;`ServerManagerApp` 用委托 + 同名瘦转发方法消费它们,使约 112 个既有调用点与 34 条静态断言不必同时改写。根 `server_manager.py` 保留为薄壳入口(包与模块同名时 **包优先**,已实测),保证旧快捷方式与 PyInstaller spec 入口不破。

**Tech Stack:** Python 3.13 / Tkinter / NSSM / PyInstaller 6.19 / pytest

**Spec:** `docs/superpowers/specs/2026-09-28-server-manager-package-split-design.md`

## Global Constraints

- 基线:`main` @ `e60c82e5`(A 止血 + B 去重已完成),文件 3082 行、`ServerManagerApp` 单类 2266 行、112 方法。
- 操作层模块(service_ops/windows_ops/redis_ops/dev_mode)**不得 import tkinter、不得 import app**。
- 包与根模块同名时**包优先**(已实测):根 `server_manager.py` 只作为入口薄壳,行数 ≤ 20。
- **每步都必须能回滚**:一步一提交;步骤 1 的回滚目标是 `e60c82e5`。
- 每步完成判据(缺一不可):① `python -c "import server_manager"` 冒烟;② 34 条 GUI 断言全绿;③ 全量 GUI 断言用 `--noconftest` 跑(见下"测试运行方式")。
- **测试运行方式**:`python -m pytest tests/test_server_manager_*.py --noconftest -p no:cacheprovider -q`。这些断言只读文本、不需要数据库;`--noconftest` 可避开 `tests/conftest.py` 的会话级 autouse DB fixture(它会被并发测试运行抢占而挂起,实测 19 分钟不返回)。
- PyInstaller 打包后 EXE 名不变(`ERP服务器管理器_v5.33`),`uac_admin=True` 保持。
- 另一会话可能并行修改同一工作树:每次动手前 `git status --short | grep -v frontend-vite` 确认只有自己的改动;发现外来改动即停下询问。
- 所有提交信息末尾附 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`。

## Review Focus

- **根入口与包同名导致离线/双击启动失败:** 用户双击 EXE(无 Python、无 CWD)时,`_get_project_dir` 的**非冻结分支**(`Path(__file__).resolve().parent`)在包化后会指向 `server_manager/` 而非仓库根 → 服务名/日志路径全错。Task 1 必须同时改掉该分支并**实测 EXE 启动**。
- **PyInstaller 对同名脚本+包的收集:** 分析入口 `server_manager.py` 会 import 同名包;若冻结后解析到脚本自身会 `ImportError`。Task 1 的 EXE 重建+启动是硬门;若失败,回退方案是把包改名为 `erp_manager/`(Task 1 内说明)。
- **静态断言静默丢失:** 34 条断言逐个迁移,迁移后**总数不减**;每步跑一次并对比条数。
- **dev_mode 状态桥断裂:** `_mode`/`_process`/`_frontend_process` 在 app 侧 ~50 处被读写(UI 判定、崩溃检测)。Task 5 用属性桥承载读写,漏掉写点会让 `check_server_status` 误判崩溃。
- **并发会话踩踏:** 每步 `git status` 前置检查;一旦发现外来改动立刻停手问用户,不要 stash(见记忆 `never-stash-user-worktree-changes`)。

---

### Task 1: 包骨架 + 入口薄壳 + 常量/契约/控件迁入

**Files:**
- Create: `server_manager/__init__.py`、`server_manager/constants.py`、`server_manager/action_gate.py`、`server_manager/widgets.py`、`server_manager/app.py`
- Modify: `server_manager.py`(3082 行 → ≤20 行薄壳)
- Test: `tests/test_sm_package_layout.py`(新建)

**Interfaces:**
- Consumes: 无(首个任务)
- Produces: `server_manager.app.main()`(入口)、`server_manager.app.ServerManagerApp`、`server_manager.constants._SVC_ALL: tuple[str, ...]`、`server_manager.action_gate.ActionGate`、`server_manager.action_gate._ActionCancelled`、`server_manager.widgets.RoundedButton`/`StatusBadge`

- [ ] **Step 1: 写失败测试**

`tests/test_sm_package_layout.py`:

```python
"""包化布局的静态断言(只读文本/路径,不 import tkinter,保证 CI 可跑)。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "server_manager"


def test_package_files_exist() -> None:
    for name in ("__init__.py", "constants.py", "action_gate.py", "widgets.py", "app.py"):
        assert (PKG / name).is_file(), f"缺少 server_manager/{name}"


def test_root_entry_is_thin_shim() -> None:
    text = (ROOT / "server_manager.py").read_text(encoding="utf-8")
    assert "from server_manager.app import main" in text
    assert len(text.splitlines()) <= 20, "根入口必须保持薄壳(≤20 行)"


def test_constants_hold_service_set() -> None:
    text = (PKG / "constants.py").read_text(encoding="utf-8")
    for sym in ("_SVC_API", "_SVC_ARQ", "_SVC_WEB", "_SVC_REDIS_CACHE", "_SVC_REDIS_BROKER", "_SVC_ALL"):
        assert sym in text, f"constants.py 缺 {sym}"


def test_widgets_and_gate_moved_out_of_app() -> None:
    app_text = (PKG / "app.py").read_text(encoding="utf-8")
    for cls in ("class RoundedButton", "class StatusBadge", "class ActionGate", "class _ActionCancelled"):
        assert cls not in app_text, f"{cls} 应已迁出 app.py"
    assert "class RoundedButton" in (PKG / "widgets.py").read_text(encoding="utf-8")
    assert "class ActionGate" in (PKG / "action_gate.py").read_text(encoding="utf-8")


def test_project_dir_probe_is_package_aware() -> None:
    """非冻结分支必须仍指向仓库根,而不是 server_manager/ 包目录。"""
    app_text = (PKG / "app.py").read_text(encoding="utf-8")
    assert "parents[1]" in app_text or "parent.parent" in app_text, \
        "包化后 _get_project_dir 的 __file__ 上溯层数未适配"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sm_package_layout.py --noconftest -p no:cacheprovider -q`
Expected: 5 failed(`server_manager/` 目录不存在)

- [ ] **Step 3: 建包并迁移三类成员**

按现有行号切分(行号基于 `e60c82e5`):

1. **constants.py** —— 从 `server_manager.py` 迁入模块级常量:`_IS_WINDOWS`/`_PROJECT_DIR`/`_FRONTEND_DIR`/`_API_PORT`/`_WEB_PORT`/`_REDIS_PORT`/`_REDIS_BROKER_PORT`/`_SVC_*`/`_SVC_ALL`/`_SVC_DEPENDS`/`_NSSM_CANDIDATES`/`_REDIS_CONF_PATHS`/`_REDIS_EXE_PATHS`/`_HTTP_DIRECT`/`_PYTHON_EXE`/`_VERSION`/`_WINDOW_TITLE`;
2. **action_gate.py** —— 迁入 `_ActionCancelled`(L309-315)与 `ActionGate`(L318-425),原样复制,只补 `import threading, time, contextlib`;
3. **widgets.py** —— 迁入 `RoundedButton`(L428-630)、`StatusBadge`(L651-776)、颜色助手 `_font_exists`/`_shift_color`/`_lerp_color`/`_hex_to_rgb` 等(以实际存在者为准),补 `import tkinter as tk`;
4. **app.py** —— 其余全部内容迁入(含 `ServerManagerApp`、`_taskkill*`、`_is_prod_runner_cmdline`、`_get_project_dir`、`_ensure_single_instance`、`_activate_existing_window`、`_get_python_executable`、`_validate_python_exe`、`_create_tray_icon_image`、`main`),顶部改为 `from server_manager.constants import *` 风格的**显式导入**(不要 `import *`)+ `from server_manager.widgets import RoundedButton, StatusBadge` + `from server_manager.action_gate import ActionGate, _ActionCancelled`;
5. **`_get_project_dir` 的非冻结分支** 由 `Path(__file__).resolve().parent` 改为 `Path(__file__).resolve().parents[1]`(包内文件 → 仓库根);
6. **`__init__.py`**:`from server_manager.app import main` + `__all__ = ["main"]`;
7. **根 `server_manager.py` 改为薄壳**:

```python
"""ERP 服务器管理器入口(薄壳)。

实现已迁入 server_manager/ 包;本文件只为保持以下入口不变:
  · 双击桌面快捷方式 / PyInstaller spec 的 Analysis(['server_manager.py'])
  · `python server_manager.py`
包与模块同名时 **包优先**(已实测),故 `from server_manager.app import main` 解析到包。
"""
from server_manager.app import main

if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 跑测试与全量回归**

Run: `python -m pytest tests/test_sm_package_layout.py --noconftest -p no:cacheprovider -q`
Expected: 5 passed

Run: `python -m pytest tests/test_server_manager_dedup.py tests/test_server_manager_stop_scope.py tests/test_server_manager_backup_badge.py tests/test_server_manager_v533_stop.py tests/test_server_manager_erp_web.py --noconftest -p no:cacheprovider -q`
Expected: **34 passed**(这 5 个文件仍读 `server_manager.py`;此刻它是薄壳,断言会失败 —— **本步骤先把它们的读取路径改为 `server_manager/app.py`**,计数不得低于 34)

Run: `python -c "import server_manager; print(server_manager.main)"`
Expected: 打印函数对象,无 ImportError

- [ ] **Step 5: 重建 EXE 并实测启动(硬门)**

Run: `python -m PyInstaller --clean --noconfirm server_manager.spec > /tmp/gui_build_t1.log 2>&1; echo $?`
Expected: 退出码 0,且 `/tmp/gui_build_t1.log` 含 `Build complete`

Run: `python -c "import marshal; from PyInstaller.archive.readers import CArchiveReader; c=CArchiveReader('dist/ERP服务器管理器_v5.33.exe'); e=next(n for n in c.toc if 'server_manager' in str(n)); b=marshal.dumps(c.extract(e)); print(len(b))"`
Expected: 打印字节数(入口脚本被收集)

**人工门(必须由用户执行并回报)**:双击 `dist/ERP服务器管理器_v5.33.exe` → 窗口正常出现、五服务徽章有值、日志区可滚动。**若双击失败或报 ImportError**:把包目录改名为 `erp_manager/`(同步改所有 `from server_manager.` 为 `from erp_manager.`),重复本步骤直到通过。

- [ ] **Step 6: Commit**

```bash
command git add server_manager.py server_manager/ tests/test_sm_package_layout.py tests/test_server_manager_*.py
command command git commit -m "refactor(server_manager): 包化第 1 步——建包 + 常量/契约/控件迁入 + 根入口薄壳"
```
(提交信息末尾加 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`)

---

### Task 2: windows_ops 入包(纯函数层)

**Files:**
- Create: `server_manager/windows_ops.py`
- Modify: `server_manager/app.py`(改为转发)
- Test: `tests/test_sm_windows_ops.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `server_manager.constants`
- Produces: `windows_ops.taskkill(pid, force=True, tree=True) -> None`、`taskkill_many(pids) -> None`、`is_prod_runner_cmdline(cmdline: str) -> bool`、`find_port_pids(port: int, exclude: set[str] | None = None) -> list[str]`、`kill_port_sync(port, msg_queue, exclude=None) -> None`、`collect_process_tree(root_pid) -> list[int]`、`kill_process_tree(pid) -> None`、`find_project_residual_pids(project_dir, msg_queue, exclude=()) -> list[int]`、`find_loose_prod_runner_pids(exclude=()) -> list[int]`、`kill_residual_async(msg_queue, exclude=()) -> None`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sm_windows_ops.py
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
WO = ROOT / "server_manager" / "windows_ops.py"

def test_module_exists_and_is_tk_free() -> None:
    text = WO.read_text(encoding="utf-8")
    assert "import tkinter" not in text and "from tkinter" not in text
    assert "import server_manager.app" not in text and "from server_manager.app" not in text

def test_public_api_present() -> None:
    text = WO.read_text(encoding="utf-8")
    for fn in ("def taskkill(", "def taskkill_many(", "def is_prod_runner_cmdline(",
               "def find_port_pids(", "def kill_port_sync(", "def collect_process_tree(",
               "def kill_process_tree(", "def find_project_residual_pids(",
               "def find_loose_prod_runner_pids(", "def kill_residual_async("):
        assert fn in text, f"windows_ops 缺 {fn}"

def test_port_match_is_exact_not_substring() -> None:
    """端口精确匹配回归锁: ':5002' 不得命中 ':50021'。"""
    text = WO.read_text(encoding="utf-8")
    assert "rsplit(':', 1)" in text or 'rsplit(":", 1)' in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sm_windows_ops.py --noconftest -p no:cacheprovider -q`
Expected: 3 failed(模块不存在)

- [ ] **Step 3: 实现**

把 app 中下列方法逐字迁入 `windows_ops.py` 并**改为模块级函数**(去掉 `self`,把用到的实例状态改为参数:`msg_queue`、`project_dir`、`exclude`):
`_taskkill`/`_taskkill_many`/`_is_prod_runner_cmdline`/`_collect_process_tree`/`_kill_process_tree`/`_find_port_pids`/`_kill_port_sync`/`_kill_residual_async`/`_find_project_residual_pids`/`_find_loose_prod_runner_pids`。
app 内保留同名**瘦转发**方法,签名与行为不变:

```python
    def _find_port_pids(self, port, exclude=None):
        return windows_ops.find_port_pids(port, exclude)

    def _kill_process_tree(self, pid):
        return windows_ops.kill_process_tree(pid)
    # 其余同理，逐一转发；_find_project_residual_pids/_kill_residual_async 传
    # self._msg_queue 与 _PROJECT_DIR
```

- [ ] **Step 4: 跑测试与全量回归**

Run: `python -m pytest tests/test_sm_windows_ops.py tests/test_server_manager_dedup.py tests/test_server_manager_stop_scope.py tests/test_server_manager_backup_badge.py tests/test_server_manager_v533_stop.py tests/test_server_manager_erp_web.py --noconftest -p no:cacheprovider -q`
Expected: **≥37 passed**(3 新 + 34 既有;`test_server_manager_v533_stop.py` 的前 3 条端口用例必须仍绿)

- [ ] **Step 5: Commit**

```bash
command git add server_manager/ tests/test_sm_windows_ops.py
command command git commit -m "refactor(server_manager): 包化第 2 步——windows_ops(进程/端口纯函数层)入包"
```

---

### Task 3: redis_ops 入包(自持 redis_process 状态)

**Files:**
- Create: `server_manager/redis_ops.py`
- Modify: `server_manager/app.py`(转发 + 属性桥)
- Test: `tests/test_sm_redis_ops.py`(新建)

**Interfaces:**
- Consumes: `windows_ops.kill_port_sync`(若用到)、`constants._REDIS_PORT`/`_REDIS_BROKER_PORT`/`_SVC_REDIS_*`
- Produces: `class RedisOps`:`__init__(self, msg_queue, gate, project_dir)`;方法 `ping(port, password) -> bool`、`is_redis_running() -> bool`、`is_broker_running() -> bool`、`redis_service_state(name) -> str`、`start_redis_via_service(name)`、`start_redis()`、`ensure_redis_broker() -> bool`、`stop_redis() -> None`、`get_env_value(key) -> str | None`;**属性 `redis_process`**(原 `self._redis_process` 的拥有者)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sm_redis_ops.py
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
RO = ROOT / "server_manager" / "redis_ops.py"

def test_module_exists_and_is_tk_free() -> None:
    text = RO.read_text(encoding="utf-8")
    assert "tkinter" not in text
    assert "from server_manager.app" not in text

def test_class_and_state_owner() -> None:
    text = RO.read_text(encoding="utf-8")
    assert "class RedisOps" in text
    for m in ("def ping(", "def is_redis_running(", "def is_broker_running(",
              "def redis_service_state(", "def start_redis(", "def ensure_redis_broker(",
              "def stop_redis(", "def get_env_value("):
        assert m in text, f"RedisOps 缺 {m}"
    assert "self.redis_process" in text, "redis_process 应由 RedisOps 自持"

def test_resp_single_implementation() -> None:
    text = RO.read_text(encoding="utf-8")
    assert text.count("sock.sendall") == 3, "RESP 报文应只此一处(B2 回归锁)"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sm_redis_ops.py --noconftest -p no:cacheprovider -q`
Expected: 3 failed

- [ ] **Step 3: 实现**

1. 把 `_redis_ping`/`_is_redis_running`/`_is_broker_running`/`_redis_service_state`/`_start_redis_via_service`/`_start_redis`/`_start_redis_process`/`_ensure_redis_broker`/`_stop_redis`/`_get_env_value` 迁入 `RedisOps`,把 `self._msg_queue`→`self._msg_queue`(构造注入)、`self._gate`→`self._gate`、`self._is_redis_running()`→`self.is_redis_running()`、`self._redis_process`→`self.redis_process`;
2. `_start_redis_via_service` 用到的 `self._wait_service(...)` 改为注入的回调 `self._wait_service: Callable`(构造参数),Task 4 之前先由 app 传入 `self._wait_service`;
3. app 内新增 `self.redis = RedisOps(self._msg_queue, self._gate, _PROJECT_DIR, wait_service=self._wait_service)`,并**属性桥**:

```python
    @property
    def _redis_process(self):
        return self.redis.redis_process

    @_redis_process.setter
    def _redis_process(self, value):
        self.redis.redis_process = value
```
4. app 内保留全部同名瘦转发(`_is_redis_running`→`return self.redis.is_redis_running()` 等),既有调用点不改。

- [ ] **Step 4: 跑测试与全量回归**

Run: `python -m pytest tests/test_sm_redis_ops.py tests/test_server_manager_dedup.py tests/test_server_manager_stop_scope.py tests/test_server_manager_backup_badge.py tests/test_server_manager_v533_stop.py tests/test_server_manager_erp_web.py --noconftest -p no:cacheprovider -q`
Expected: **≥40 passed**

- [ ] **Step 5: Commit**

```bash
command git add server_manager/ tests/test_sm_redis_ops.py
command command git commit -m "refactor(server_manager): 包化第 3 步——redis_ops(探活/启停,自持 redis_process)"
```

---

### Task 4: service_ops 入包(NSSM/sc 服务层,最大一块)

**Files:**
- Create: `server_manager/service_ops.py`
- Modify: `server_manager/app.py`(转发)
- Test: `tests/test_sm_service_ops.py`(新建)

**Interfaces:**
- Consumes: `constants._SVC_ALL`/`_SVC_DEPENDS`、`windows_ops.*`
- Produces: `class ServiceOps`:`__init__(self, msg_queue, gate, project_dir, log_message, nssm_finder)`;方法 `find_nssm()`、`run_capture(args, timeout=20) -> tuple[int, str]`、`decode_output(raw, *, strip=False) -> str`、`svc_state(name) -> str`、`svc_pid(name)`、`svc_installed(name) -> bool`、`wait_service(name, target, timeout, *, checkpoint=True, interval=1.0, state_fn=None) -> str`、`wait_service_stopped(name, timeout=45) -> bool`、`wait_service_running(name, timeout=25) -> tuple[bool, str, int | None]`、`start_one_service(name, timeout=25)`、`managed_service_pids() -> set`、`stop_managed_services() -> tuple[int, set]`、`service_cmd_sync(verb) -> None`、`nssm_install(...) -> bool`、`apply_depends(name, depends) -> None`、`uninstall_services_flow(nssm) -> None`、`ensure_production_stopped() -> tuple[bool, str | None, bool]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sm_service_ops.py
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SO = ROOT / "server_manager" / "service_ops.py"

def test_module_exists_and_is_tk_free() -> None:
    text = SO.read_text(encoding="utf-8")
    assert "tkinter" not in text
    assert "from server_manager.app" not in text

def test_public_api_present() -> None:
    text = SO.read_text(encoding="utf-8")
    for m in ("def find_nssm(", "def run_capture(", "def decode_output(", "def svc_state(",
              "def wait_service(", "def stop_managed_services(", "def managed_service_pids(",
              "def service_cmd_sync(", "def nssm_install(", "def ensure_production_stopped("):
        assert m in text, f"ServiceOps 缺 {m}"

def test_stop_paths_use_svc_all() -> None:
    """A 的回归锁随之迁移:停止/重启/受管 PID 排除仍按 _SVC_ALL 迭代。"""
    text = SO.read_text(encoding="utf-8")
    assert text.count("for name in _SVC_ALL") >= 3

def test_env_written_elementwise() -> None:
    """A 的回归锁随之迁移:AppEnvironmentExtra 逐元素写入。"""
    text = SO.read_text(encoding="utf-8")
    assert "isinstance(val, list)" in text

def test_single_decoder_and_poll() -> None:
    """B 的回归锁随之迁移:解码器唯一、轮询原语唯一。"""
    text = SO.read_text(encoding="utf-8")
    assert text.count("gb18030") <= 1
    assert "def wait_service(" in text
    app = (ROOT / "server_manager" / "app.py").read_text(encoding="utf-8")
    assert "deadline = time.monotonic()" not in app or app.count("deadline = time.monotonic()") <= 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sm_service_ops.py --noconftest -p no:cacheprovider -q`
Expected: 5 failed

- [ ] **Step 3: 实现**

1. 迁入 18 个方法(见 Interfaces 列表),`self._msg_queue`→注入的 `msg_queue`、`self._gate`→注入的 `gate`、`self.log_message`→注入的 `log_message`、`self._find_nssm`→`self.find_nssm`;
2. app 内:`self.svc = ServiceOps(msg_queue=self._msg_queue, gate=self._gate, project_dir=_PROJECT_DIR, log_message=self.log_message, nssm_finder=...)`;
3. app 内保留同名瘦转发(`_svc_state`→`self.svc.svc_state(name)`、`_wait_service`→`self.svc.wait_service(...)`、`_nssm_install`→`self.svc.nssm_install(...)` 等),既有调用点不改;
4. **`_decode_output` 是 `@staticmethod`,转发时保持静态语义**。

- [ ] **Step 4: 跑测试与全量回归**

Run: `python -m pytest tests/test_sm_service_ops.py tests/test_server_manager_dedup.py tests/test_server_manager_stop_scope.py tests/test_server_manager_backup_badge.py tests/test_server_manager_v533_stop.py tests/test_server_manager_erp_web.py --noconftest -p no:cacheprovider -q`
Expected: **≥45 passed**

Run: `python -m ruff check server_manager/`
Expected: 无新增错误

- [ ] **Step 5: Commit**

```bash
command git add server_manager/ tests/test_sm_service_ops.py
command command git commit -m "refactor(server_manager): 包化第 4 步——service_ops(NSSM/sc 服务层)入包"
```

---

### Task 5: dev_mode 入包(状态拥有者 + app 侧属性桥)

**Files:**
- Create: `server_manager/dev_mode.py`
- Modify: `server_manager/app.py`(转发 + 属性桥,约 50 处读写走桥)
- Test: `tests/test_sm_dev_mode.py`(新建)

**Interfaces:**
- Consumes: `windows_ops.kill_process_tree`/`kill_port_sync`、`service_ops.ensure_production_stopped`、`redis_ops.stop_redis`
- Produces: `class DevModeOps`:`__init__(self, msg_queue, gate, project_dir, svc, redis)`;方法 `start_dual_server(label)`、`start_dual_flow(...)`、`start_dual_thread(...)`、`start_dual_worker(...)`、`stop_dual_mode_async()`、`stop_dual_flow(label)`、`restart_dual_thread(label)`、`terminate_dev_processes(reason='', *, wait=True) -> bool`、`ensure_development_stopped() -> tuple[bool, str | None, bool]`、`read_stdout(proc)`、`read_frontend_stdout(proc)`;**属性 `process`、`frontend_process`、`mode`、`current_mode_key`、`startup_progress`、`startup_steps`、`startup_current_step`**

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sm_dev_mode.py
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DM = ROOT / "server_manager" / "dev_mode.py"
APP = ROOT / "server_manager" / "app.py"

def test_module_exists_and_is_tk_free() -> None:
    text = DM.read_text(encoding="utf-8")
    assert "tkinter" not in text
    assert "from server_manager.app" not in text

def test_class_owns_state() -> None:
    text = DM.read_text(encoding="utf-8")
    assert "class DevModeOps" in text
    for attr in ("self.process", "self.frontend_process", "self.mode", "self.current_mode_key"):
        assert attr in text, f"DevModeOps 应自持 {attr}"

def test_single_terminate_primitive() -> None:
    """B4 回归锁随之迁移:终止循环只应有一处。"""
    text = DM.read_text(encoding="utf-8")
    assert "def terminate_dev_processes(" in text
    assert text.count("for proc, name in ((self._frontend_process") <= 0

def test_app_bridges_state() -> None:
    """app 侧必须以属性桥读写 dev_mode 的状态,否则 UI 崩溃检测会误判。"""
    text = APP.read_text(encoding="utf-8")
    for prop in ("def _mode(", "def _process(", "def _frontend_process("):
        assert prop in text, f"app.py 缺属性桥 {prop}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sm_dev_mode.py --noconftest -p no:cacheprovider -q`
Expected: 4 failed

- [ ] **Step 3: 实现**

1. 迁入 dev/dual 相关方法:`_start_dual_server`/`_start_dual_flow`/`_start_dual_worker`/`_start_dual_thread`/`_stop_dual_mode_async`/`_stop_dual_flow`/`_restart_dual_thread`/`_on_dual_started`/`_on_dual_failed`/`_terminate_dev_processes`/`_ensure_development_stopped`/`_read_stdout`/`_read_frontend_stdout`;`self._process`→`self.process`、`self._mode`→`self.mode`、`self._frontend_process`→`self.frontend_process`、`self._current_mode_key`→`self.current_mode_key`、`self._startup_*`→`self.startup_*`;
2. app 内**属性桥**(读写都要,共 6 个属性):

```python
    @property
    def _mode(self):
        return self.dev.mode

    @_mode.setter
    def _mode(self, value):
        self.dev.mode = value
    # _current_mode_key / _process / _frontend_process / _startup_* 同理
```
3. app 内保留同名转发(`_terminate_dev_processes`→`self.dev.terminate_dev_processes(...)` 等);
4. 自检:在 `check_server_status`/`_update_all_ui`/`_apply_hosting_data` 附近逐个确认 `self._mode`/`self._process` 的读写仍经属性桥解析(运行 Step 4 的断言 + 导入冒烟)。

- [ ] **Step 4: 跑测试与全量回归**

Run: `python -m pytest tests/test_sm_dev_mode.py tests/test_server_manager_dedup.py tests/test_server_manager_stop_scope.py tests/test_server_manager_backup_badge.py tests/test_server_manager_v533_stop.py tests/test_server_manager_erp_web.py --noconftest -p no:cacheprovider -q`
Expected: **≥49 passed**

Run: `python -c "import server_manager; print(server_manager.main)"`
Expected: 正常打印

- [ ] **Step 5: 重建 EXE 并实测(硬门)**

Run: `python -m PyInstaller --clean --noconfirm server_manager.spec > /tmp/gui_build_t5.log 2>&1; echo $?`
Expected: 0 且含 `Build complete`

**人工门**:双击新 EXE → 启动开发模式 → 停止 → 重启 → 紧急停止,四项 UI 状态与日志均正确。

- [ ] **Step 6: Commit**

```bash
command git add server_manager/ tests/test_sm_dev_mode.py
command command git commit -m "refactor(server_manager): 包化第 5 步——dev_mode(自持进程/模式状态 + app 属性桥)"
```

---

### Task 6: 规模门禁与函数长度门禁收严

**Files:**
- Modify: `scripts/file_size_gate.py`、`scripts/check_function_length.py`、`.github/workflows/ci-cd.yml`
- Test: `tests/test_gates_cover_repo_root.py`(新建)

**Interfaces:**
- Consumes: 无
- Produces: 门禁扫描范围含仓库根顶层 `.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_gates_cover_repo_root.py
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

def test_file_size_gate_scans_repo_root() -> None:
    text = (ROOT / "scripts" / "file_size_gate.py").read_text(encoding="utf-8")
    assert 'glob("*.py")' in text, "file_size_gate 未纳入仓库根顶层 .py"

def test_function_length_gate_scans_repo_root() -> None:
    text = (ROOT / "scripts" / "check_function_length.py").read_text(encoding="utf-8")
    assert "PROJECT_ROOT" in text and "DEFAULT_SCAN_DIRS" in text

def test_ci_uses_all_mode() -> None:
    text = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    assert "file_size_gate.py --all" in text, "CI 仍在用会空转的 git-diff 模式"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_gates_cover_repo_root.py --noconftest -p no:cacheprovider -q`
Expected: 3 failed

- [ ] **Step 3: 实现**

1. `scripts/file_size_gate.py`:在 `_all_py_files()`(L104 起)的 `SCAN_DIRS` 循环**之后**追加仓库根顶层扫描:

```python
    # 顶层 .py(仓库根):此前遗漏,导致全仓最大的 server_manager.py 逃过门禁
    for p in PROJECT_ROOT.glob("*.py"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        files.append(p)
```
(以文件内实际的 `PROJECT_ROOT`/`EXCLUDE_DIRS` 命名为准)

2. `scripts/check_function_length.py`:`DEFAULT_SCAN_DIRS` 由 `[PROJECT_ROOT / "fastapi_app"]` 改为 `[PROJECT_ROOT / "fastapi_app", PROJECT_ROOT]`,并在 `scan()` 里对根目录**只取顶层 `*.py`**(避免递归进 `frontend-vite/node_modules`):

```python
    for d in scan_dirs:
        if d == PROJECT_ROOT:
            candidates = d.glob("*.py")
        else:
            candidates = d.rglob("*.py")
```
3. `.github/workflows/ci-cd.yml` L164-166 改为:

```yaml
    - name: Run file size gate (block new god-classes)
      # 阈值取自 pyproject.toml [tool.code-quality] max_file_size，此处不再硬编码
      # --all：git-diff 模式在 CI 的干净检出里恒为空(实测),等于空转;--all 显式全量扫描
      run: python scripts/file_size_gate.py --all
```

- [ ] **Step 4: 跑测试与门禁**

Run: `python -m pytest tests/test_gates_cover_repo_root.py --noconftest -p no:cacheprovider -q`
Expected: 3 passed

Run: `python scripts/file_size_gate.py --all`
Expected: 报出的超限文件里**不含** `server_manager/app.py`(拆分后 ~1200 行);若仍有 `tests/test_outsource.py`(1622 行,存量)属既有基线,不属本任务

Run: `python scripts/check_function_length.py server_manager/app.py`
Expected: 输出超长函数清单(预期仅 `_apply_hosting_data` 153 行 —— 函数级收严属 D,本任务不修)

- [ ] **Step 5: Commit**

```bash
command git add scripts/file_size_gate.py scripts/check_function_length.py .github/workflows/ci-cd.yml tests/test_gates_cover_repo_root.py
command command git commit -m "chore(gates): 规模/函数长度门禁纳入仓库根,CI 改 --all 修掉空转的 git-diff 模式"
```

---

## Self-Review

**1. Spec coverage:**
- §2 目标结构(9 个模块)→ Task 1(constants/action_gate/widgets/app/__init__)、Task 2(windows_ops)、Task 3(redis_ops)、Task 4(service_ops)、Task 5(dev_mode)✓
- §3.1 依赖方向(操作层不 import app/tk)→ Task 2/3/4/5 每条都有 `test_..._is_tk_free` 断言 ✓
- §3.2 入口兼容(根薄壳 ≤20 行、包优先、`_get_project_dir` 适配)→ Task 1 Step 3 第 5/7 点 + Step 5 EXE 硬门 + `test_project_dir_probe_is_package_aware` ✓
- §3.3 断言迁移总数不减 → 每任务 Step 4 给出**递增的通过条数下限**(34→37→40→45→49)✓
- §4 六步迁移 + 每步验证清单 → 与 Task 1-6 一一对应 ✓;§4 的"回滚"→ Global Constraints 声明 ✓
- §5 门禁收严细节 → Task 6 ✓(根文件扫描、CI `--all`、函数长度含根、函数级留给 D)
- §6 风险(打包断裂/断言丢失/并发会话)→ Review Focus 逐条落地 ✓

**2. Placeholder scan:** 无 TBD/TODO;每个 Step 都给出可执行命令或完整代码块。Task 3 的"注入 `wait_service` 回调"给出了构造签名与 app 侧接线代码。

**3. Type consistency:** `wait_service(name, target, timeout, *, checkpoint=True, interval=1.0, state_fn=None) -> str` 在 Task 4 定义、Task 3 以回调消费,签名一致;`terminate_dev_processes(reason='', *, wait=True) -> bool` 在 Task 5 定义且与 B4 实现一致;`ensure_production_stopped() -> tuple[bool, str | None, bool]` 与现有 3 元组契约一致(该契约在 `_ensure_production_stopped` docstring 里被标为 P0-1 修复点)。

**4. Review Focus 与测试对应:** 五条 Review Focus 各自落到:`test_project_dir_probe_is_package_aware`(根入口/项目根)、Task 1 Step 5 的 EXE 硬门(PyInstaller 同名)、每任务 Step 4 的递增条数(断言丢失)、`test_app_bridges_state`(dev_mode 状态桥)、Global Constraints + Review Focus 的 `git status` 前置检查(并发会话)。

**已知不做(留给 D):** `_apply_hosting_data` 153 行函数级拆分;消费侧去掉二次推导(ARQ 徽章改用 `backup.arq_ok`、Redis 判活收敛到单一契约)。

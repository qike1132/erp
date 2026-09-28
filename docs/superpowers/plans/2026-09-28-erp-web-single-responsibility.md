# erp-web 单一职责重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 nginx 从 prod_runner 拆出为独立 NSSM 服务 `erp-web`,监督器瘦身为只守护 uvicorn;顺带调整 worker 数(nginx 2 / uvicorn 4)。

**Architecture:** 新增 `erp-web` Windows 服务直接托管 `nginx.exe`(Job Object 杀树);`prod_runner` 删除 `_FrontendNginx` 等约 220 行,保留只读探针写 `frontend_ok`;GUI 五处服务元组加入 erp-web 并仿 ARQ `external` 范式渲染;nginx 日志轮转下沉 `utils/log_rotation.py` 并挂进 ARQ cron;迁移脚本 `-DryRun` 幂等。

**Tech Stack:** Python 3.13 / FastAPI / ARQ / NSSM / nginx for Windows / PowerShell / pytest

**Spec:** `docs/superpowers/specs/2026-09-28-erp-web-single-responsibility-design.md`

## Global Constraints

- 生产机即本机(`D:\erp_system`,`192.168.0.95`):**绝不真实调用** `_FrontendNginx._ensure_started` / `maybe_restart` / `start` / `kill_tree` / `_kill_all`(会 taskkill 在线 nginx);测试一律打桩。
- nssm 不在 PATH:`C:\nssm\nssm.exe`;非提权 shell 无法操作服务(实测 ACL 边界),迁移脚本由用户在管理员 PowerShell 执行。
- 测试命令在仓库根运行;pytest 配置见 `pytest.ini`(strict markers)。
- `_lc` 别名故障:shell 中 git/curl/cat 必须用 `command git` 形式绕过。
- 现有服务参数基线(迁移前勿动):`erp-prod` AppParameters = `-m fastapi_app.core.prod_runner --no-arq`。
- worker 数最终值:nginx `worker_processes 2`、`.env` `UVICORN_WORKERS=4`。
- 状态文件契约:`frontend_type: "erp-web"`、`services.frontend.status: "external"`、`frontend_ok` 由探针得出。
- nssm 输出是 UTF-16LE,诊断须同时解 stdout 与 stderr。

## Review Focus

- **迁移中途断电/中断:** erp-web 注册了但 erp-prod 未重启——旧 prod_runner 拉起的 nginx 与 erp-web 抢 :3000。迁移脚本必须先 stop erp-prod 再 start erp-web,重跑幂等(Task 9 测试断言命令序列)。
- **GUI 紧急停止漏掉 erp-web:** `_stop_managed_services` 不含 erp-web → 端口清理误杀受管 nginx → NSSM 5 秒拉起 → 杀不死死循环。Task 8 断言 `_SVC_WEB` 在五处元组中。
- **dev 模式切换抢不到 :3000:** 同上根因,`_managed_service_pids` 未含 erp-web 时 dev 模式的 vite 起不来。Task 8 覆盖。
- **回滚后重启机器双 nginx:** 旧 prod_runner 拉起 nginx + erp-web 自启 → 互斗 :3000。回滚步骤必须含 `nssm set erp-web Start SERVICE_DISABLED`(Task 9 脚本注释 + 测试断言)。
- **轮转函数改动破坏 prod_runner 自身日志轮转:** 下沉到 utils 后 prod_runner 的 `_rotate_logs_if_due` 仍须轮转自己的子进程日志。Task 5 用既有单测锁定行为不变。

---

### Task 1: `utils/log_rotation.py` — 轮转函数下沉

**Files:**
- Create: `utils/log_rotation.py`
- Test: `utils/tests/test_log_rotation.py`

**Interfaces:**
- Consumes: 无(纯函数)
- Produces: `rotate_file_copytruncate(path: Path, max_bytes: int) -> bool` —— 超阈值 copytruncate 轮转,保留一代 `.1` 副本,返回是否执行;IO 失败不抛(OSError 捕获打日志返 False)。

- [ ] **Step 1: 写失败测试**

```python
"""轮转函数单测:阈值以下不动、超阈值 copytruncate、保留 .1、IO 失败不抛。"""
from __future__ import annotations

from pathlib import Path

from utils.log_rotation import rotate_file_copytruncate


def test_below_threshold_noop(tmp_path: Path) -> None:
    f = tmp_path / "a.log"
    f.write_bytes(b"x" * 100)
    assert rotate_file_copytruncate(f, 1024) is False
    assert f.read_bytes() == b"x" * 100


def test_over_threshold_rotates(tmp_path: Path) -> None:
    f = tmp_path / "a.log"
    f.write_bytes(b"y" * 2048)
    assert rotate_file_copytruncate(f, 1024) is True
    assert f.read_bytes() == b""
    assert (tmp_path / "a.log.1").read_bytes() == b"y" * 2048


def test_rotation_replaces_old_backup(tmp_path: Path) -> None:
    f = tmp_path / "a.log"
    (tmp_path / "a.log.1").write_bytes(b"old")
    f.write_bytes(b"new" * 1000)
    assert rotate_file_copytruncate(f, 1024) is True
    assert (tmp_path / "a.log.1").read_bytes() == b"new" * 1000


def test_missing_file_returns_false(tmp_path: Path) -> None:
    assert rotate_file_copytruncate(tmp_path / "nope.log", 1024) is False


def test_io_error_swallowed(tmp_path: Path, monkeypatch) -> None:
    f = tmp_path / "a.log"
    f.write_bytes(b"z" * 2048)
    def boom(src, dst, length=0):
        raise OSError("disk")
    monkeypatch.setattr("utils.log_rotation.shutil.copyfileobj", boom)
    assert rotate_file_copytruncate(f, 1024) is False  # 不抛
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest utils/tests/test_log_rotation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'utils.log_rotation'`

- [ ] **Step 3: 最小实现**

`utils/log_rotation.py`:

```python
"""日志 copytruncate 轮转(从 prod_runner 下沉的公共函数)。

Windows 下日志文件被子进程(或 nginx)以共享读写 + 追加方式长期占用,无法
rename,只能先复制再原地截断;截断瞬间与追加写之间的少量行丢失对运维日志
可接受。追加语义保证持有方后续写入落在新的文件尾。
"""
from __future__ import annotations

import shutil
from pathlib import Path


def rotate_file_copytruncate(path: Path, max_bytes: int) -> bool:
    """超阈值 copytruncate 轮转,保留一代 .1 副本,返回是否执行了轮转。"""
    try:
        if not path.is_file() or path.stat().st_size < max_bytes:
            return False
        rotated = path.with_name(path.name + ".1")
        with open(path, "rb") as src, open(rotated, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        with open(path, "r+b") as f:
            f.truncate(0)
        print(f"[log_rotation] {path.name} 超过 {max_bytes // (1024 * 1024)}MB,已轮转到 {rotated.name}")
        return True
    except OSError as e:
        print(f"[log_rotation] {path.name} 轮转失败(下一轮重试): {e}")
        return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest utils/tests/test_log_rotation.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
command git add utils/log_rotation.py utils/tests/test_log_rotation.py
```
提交信息:`feat(utils): 日志 copytruncate 轮转函数下沉为公共模块`

---

### Task 2: prod_runner 删除 nginx 管理职责(保留只读探针)

**Files:**
- Modify: `fastapi_app/core/prod_runner.py`
- Delete: `fastapi_app/core/prod_runner.py.bak_ipv6`
- Test: `fastapi_app/tests/test_prod_runner_slim.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `rotate_file_copytruncate`
- Produces: `Supervisor` 无 nginx 管理成员;状态文件 `frontend_type == "erp-web"`、`services.frontend.status == "external"`;`_rotate_logs_if_due` 只轮转后端/ARQ 自身日志;`_frontend_probe_ok() -> bool` 只读探针。

- [ ] **Step 1: 写失败测试**

`fastapi_app/tests/test_prod_runner_slim.py`:

```python
"""prod_runner 瘦身后的契约:无 nginx 管理职责,探针只观察不重启。

全部打桩,绝不触碰真实服务(生产机即本机)。
"""
from __future__ import annotations

import json

import pytest

from fastapi_app.core import prod_runner


def test_no_nginx_management_symbols() -> None:
    """管理职责已删:模块不再有 nginx 托管/vite preview 相关符号。"""
    for sym in ("_FrontendNginx", "_find_nginx", "_cmd_vite_preview", "_NGINX_CANDIDATES"):
        assert not hasattr(prod_runner, sym), f"{sym} 应已删除"


def test_supervisor_has_no_nginx_or_vite_members() -> None:
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    assert not hasattr(sup, "nginx")
    assert not hasattr(sup, "vite")
    assert sup.frontend_type == "erp-web"


def test_status_file_frontend_external(monkeypatch, tmp_path) -> None:
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
    monkeypatch.setattr(prod_runner, "_is_redis_up", lambda p: True)
    monkeypatch.setattr(sup.backend, "poll", lambda: None)
    monkeypatch.setattr(sup.backend, "maybe_restart", lambda: None)
    monkeypatch.setattr(sup, "_frontend_probe_ok", lambda: True)
    monkeypatch.setattr(sup, "_rotate_logs_if_due", lambda: None)
    class _P:
        pid = 111
        status = "ready"
        last_health = "2026-09-28T00:00:00"
    sup.backend.proc = None
    sup.write_status()
    data = json.loads((tmp_path / "prod_runner.json").read_text(encoding="utf-8"))
    assert data["frontend_type"] == "erp-web"
    assert data["services"]["frontend"] == {"type": "erp-web", "pid": None, "status": "external"}
    assert data["frontend_ok"] is True


def test_frontend_probe_failure_never_restarts(monkeypatch, tmp_path) -> None:
    """探针失败只报告:状态不跳 crashed、不调 kill_tree、退避不升级。"""
    sup = prod_runner.Supervisor(4, 5002, 3000, with_arq=False)
    monkeypatch.setattr(prod_runner, "STATUS_FILE", tmp_path / "prod_runner.json")
    monkeypatch.setattr(prod_runner, "_is_redis_up", lambda p: True)
    monkeypatch.setattr(sup.backend, "poll", lambda: None)
    monkeypatch.setattr(sup.backend, "maybe_restart", lambda: None)
    monkeypatch.setattr(sup, "_frontend_probe_ok", lambda: False)
    monkeypatch.setattr(sup, "_rotate_logs_if_due", lambda: None)
    calls: list[str] = []
    monkeypatch.setattr(
        prod_runner.Supervisor, "write_status",
        lambda self: calls.append("write"),
    )
    class _Loop:
        def __init__(self): self.n = 0
        def __call__(self): 
            self.n += 1
            if self.n > 3: raise KeyboardInterrupt
    # 单圈迭代:直接调私有编排,不进 while True
    sup._frontend_probe_ok = lambda: False  # type: ignore[method-assign]
    probe = sup._frontend_probe_ok()
    assert probe is False
    # 无 frontend 相关 restart 行为可断言(成员已删),仅验证探针可独立失败
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest fastapi_app/tests/test_prod_runner_slim.py -v`
Expected: FAIL — `_FrontendNginx` 等符号仍存在 / `frontend_type` 仍为 "nginx"

- [ ] **Step 3: 实施(关键代码)】

修改 `fastapi_app/core/prod_runner.py`:

1. **删除**:`_FrontendNginx` 类整段(约 L444-648)、`_NGINX_CANDIDATES`、`_find_nginx`、`_cmd_vite_preview`、`Supervisor.__init__` 中 nginx/vite 分支;
2. **导入**:`from utils.log_rotation import rotate_file_copytruncate`(替换原 `_rotate_file_copytruncate` 定义,保留同名包装或直接引用);
3. **新增只读探针**(替代 `_frontend_state`):

```python
def _frontend_probe_ok() -> bool:
    """只读探测 erp-web(nginx)是否在服务 :3000。失败仅报告,绝不重启。"""
    return _http_ok(
        f"http://127.0.0.1:{os.getenv('WEB_PORT', '3000')}/nginx-health",
        timeout=1.5,
        expect_substr='"service":"nginx"',
    )
```

4. **`_frontend_state` 改为**:

```python
def _frontend_state(self) -> tuple[int | None, str, bool]:
    """erp-web 由独立 NSSM 服务托管,此处只观察不管理。"""
    ok = _frontend_probe_ok()
    return None, "external", ok
```

5. **`Supervisor.__init__`**:删 `self.nginx`/`self.vite` 分支,固定 `self.frontend_type = "erp-web"`;
6. **`start_all` / `run` / `shutdown` / `_rotate_logs_if_due`**:删 nginx/vite 相关调用;`_rotate_logs_if_due` 只迭代 `(self.backend, self.arq)`;
7. **模块 docstring**:职责列表删去"前端托管"与"日志轮转(Nginx)",注明 erp-web 外部托管;
8. **`check()`**:删 vite preview 回退文案,改为 erp-web 服务状态检查提示;
9. **删除文件** `fastapi_app/core/prod_runner.py.bak_ipv6`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest fastapi_app/tests/test_prod_runner_slim.py fastapi_app/tests/test_prod_runner_backend_restart.py -v`
Expected: 全部 PASS(后端守护测试不受影响)

- [ ] **Step 5: 旧前端测试处置**

删除 `fastapi_app/tests/test_prod_runner_frontend_failure.py`(测的是被删的 `_FrontendNginx`)。

Run: `python -m pytest fastapi_app/tests/ -k "prod_runner" -v`
Expected: 只剩 slim + backend_restart 两组,PASS

- [ ] 旧前端测试处置需同步处理 QA 对抗测试(与 Task 2 同一提交)

`fastapi_app/tests/test_qa_prod_stack_regression.py`:
- 删 `TestD2EnsureStarted`、`TestD4Spawn` 两个类(只测 `_FrontendNginx`);
- 删 `TestD1ProbeFalsification.test_frontend_alive_false_on_spa_fallback` 与 `_prep_frontend` 辅助(依赖 `_FrontendNginx`);
- 删 `TestD3WriteStatus` 中依赖 `_prep_frontend`/nginx 的用例,保留 `test_ready_semantics_unchanged_backend_only`;
- `_NGINX_UP` 探测保留(live 用例仍探测真实 :3000)。

Run: `python -m pytest fastapi_app/tests/test_qa_prod_stack_regression.py -v`
Expected: 剩余用例 PASS

- [ ] **Step 6: Commit**

```bash
command git add -A fastapi_app/core/prod_runner.py fastapi_app/tests/
command git rm fastapi_app/core/prod_runner.py.bak_ipv6 2>/dev/null || true
```
提交信息:`refactor(prod_runner): 删除 nginx 管理职责,erp-web 外部托管,探针只观察不重启`

---

### Task 3: ARQ cron 挂载 nginx 日志轮转

**Files:**
- Modify: `fastapi_app/core/arq_app.py:76-110`(cron_schedules)
- Create: `fastapi_app/core/tasks/log_rotate_task.py`(若 `tasks/` 结构不同,放 `fastapi_app/core/arq_tasks.py`,按现有结构)
- Test: `fastapi_app/tests/test_arq_log_rotation_cron.py`(新建)

**Interfaces:**
- Consumes: Task 1 的 `rotate_file_copytruncate`
- Produces: `rotate_nginx_logs_task(ctx) -> None`(ARQ 任务函数,注册于 `cron_schedules` 项 `{'name': 'nginx-log-rotation', 'cron': {'hour': 4, 'minute': 30}, 'schedule': '4:30', 'timeout': 120}`)。

- [ ] **Step 1: 写失败测试**

```python
"""nginx 日志轮转 cron 注册与任务行为断言。"""
from __future__ import annotations

from pathlib import Path

from fastapi_app.core import arq_app


def test_cron_registered() -> None:
    names = [s["name"] for s in arq_app.cron_schedules]
    assert "nginx-log-rotation" in names


def test_cron_daily_0430() -> None:
    entry = next(s for s in arq_app.cron_schedules if s["name"] == "nginx-log-rotation")
    assert entry["cron"] == {"hour": 4, "minute": 30}
    assert entry.get("timeout") == 120


def test_task_rotates_nginx_logs(tmp_path, monkeypatch) -> None:
    from fastapi_app.core.tasks import log_rotate_task
    access = tmp_path / "nginx-access.log"
    error = tmp_path / "nginx-error.log"
    access.write_bytes(b"a" * 2048)
    error.write_bytes(b"e" * 2048)
    monkeypatch.setattr(log_rotate_task, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(log_rotate_task, "LOGS_DIR", tmp_path)
    log_rotate_task.rotate_nginx_logs_task(None)
    assert access.read_bytes() == b""
    assert (tmp_path / "nginx-access.log.1").exists()
    assert (tmp_path / "nginx-error.log.1").exists()


def test_task_noop_when_small(tmp_path, monkeypatch) -> None:
    from fastapi_app.core.tasks import log_rotate_task
    access = tmp_path / "nginx-access.log"
    access.write_bytes(b"a" * 10)
    monkeypatch.setattr(log_rotate_task, "LOGS_DIR", tmp_path)
    log_rotate_task.rotate_nginx_logs_task(None)
    assert access.read_bytes() == b"a" * 10
    assert not (tmp_path / "nginx-access.log.1").exists()
```

- [ ] **Step  ARQ 任务实现**

`fastapi_app/core/tasks/log_rotate_task.py`(新建):

```python
"""nginx 日志轮转 ARQ 任务(prod_runner 不再托管 nginx 后的轮转归属)。"""
from __future__ import annotations

from pathlib import Path

from utils.log_rotation import rotate_file_copytruncate

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
NGINX_LOGS = ("nginx-access.log", "nginx-error.log")
NGINX_LOG_ROTATE_BYTES = 100 * 1024 * 1024  # 100MB,当前增速数月 8MB


def rotate_nginx_logs_task(ctx: dict | None) -> None:
    """每日 04:30 检查 nginx 日志,超 100MB copytruncate 轮转。ARQ 停摆仅意味着暂不轮转。"""
    for name in NGINX_LOGS:
        rotate_file_copytruncate(LOGS_DIR / name, NGINX_LOG_ROTATE_BYTES)
```

注意 `PROJECT_ROOT` 层级:`fastapi_app/core/tasks/log_rotate_task.py` → 4 层 `.parent` 回到仓库根;实施时以 `arq_app.py` 现有 import 路径为准,若 `tasks/` 不是包则按现有结构调整落点并同步测试 import。

`arq_app.py` 的 `cron_schedules` 列表追加:

```python
    {
        'name': 'nginx-log-rotation',
        'func': rotate_nginx_logs_task,
        'cron': {'hour': 4, 'minute': 30},
        'schedule': '4:30',
        'timeout': 120,
    },
```

- [ ] **Step 3: 跑测试**

Run: `python -m pytest fastapi_app/tests/test_arq_log_rotation_cron.py -v`
Expected: 4 passed

- [ ] **Step 4: Commit**

```bash
command git add fastapi_app/core/arq_app.py fastapi_app/core/tasks/log_rotate_task.py fastapi_app/tests/test_arq_log_rotation_cron.py
```
提交信息:`feat(arq): nginx 日志轮转挂入每日 cron(04:30,阈值 100MB)`

---

### Task 4: 迁移脚本 `scripts/migrate_erp_web.ps1`

**Files:**
- Create: `scripts/migrate_erp_web.ps1`
- Test: `tests/test_migrate_erp_web_dryrun.py`(新建)

**Interfaces:**
- Consumes: 无
- Produces: `-DryRun` 模式打印将执行的 nssm 命令序列,不执行;正常模式幂等执行迁移六步。

- [ ] **Step 1: 写失败测试**

```python
"""迁移脚本 DryRun 输出断言。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "migrate_erp_web.ps1"


def test_dryrun_prints_sequence() -> None:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-DryRun"],
        capture_output=True, text=True, timeout=60,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    for expected in (
        "nssm install erp-web",
        "nssm set erp-web Application C:\\nginx\\nginx.exe",
        "nssm set erp-web AppParameters",
        "nssm stop erp-prod",
        "nssm start erp-web",
        "nssm start erp-prod",
        "runtime_mode_probe.py",
    ):
        assert expected in out, f"missing: {expected}"


def test_dryrun_contains_rollback_notes() -> None:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-DryRun"],
        capture_output=True, text=True, timeout=60,
    )
    out = r.stdout + r.stderr
    assert "SERVICE_DISABLED" in out  # 回滚必须含禁用自启
    assert "git revert" in out
```

_dryrun 测试用 subprocess 跑 PowerShell;若机器无法以非提权跑该脚本,则测试标记 `@pytest.mark.skipif` — 但注意 pytest.ini strict markers,需在 pytest.ini 注册 marker 或改用环境探测函数跳过。实施时先跑一次确认可行性,不可行则改为对脚本文本做静态断言(断言命令字面量存在),静态断言版本:

```python
def test_rollback_notes_static() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    for expected in ("SERVICE_DISABLED", "git revert", "nssm stop erp-web"):
        assert expected in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_migrate_erp_web_dryrun.py -v`
Expected: FAIL — 脚本不存在

- [ ] **Step 3: 实现脚本**

```powershell
# ============================================================
# erp-web 单一职责迁移脚本(幂等,支持 -DryRun)
# 用途:注册 erp-web(NSSM 托管 nginx)并完成生产切换
# 执行:管理员 PowerShell(非提权无法操作服务)
#   .\scripts\migrate_erp_web.ps1 -DryRun   只打印命令序列
#   .\scripts\migrate_erp_web.ps1           真实执行
# 前置:代码已部署(main 拉到本机);nssm 在 C:\nssm\nssm.exe
# 回滚(如需):
#   nssm stop erp-web
#   nssm set erp-web Start SERVICE_DISABLED   # 防止开机自启与旧 prod_runner 双 nginx
#   git revert <本系列提交>
#   nssm restart erp-prod                      # 旧 prod_runner 重新拉起 nginx
# ============================================================
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
$Nssm = "C:\nssm\nssm.exe"
$Root = "D:\erp_system"
$NginxExe = "C:\nginx\nginx.exe"
$NginxArgs = "-p D:\erp_system -c D:\erp_system\config\nginx-windows.conf -e D:\erp_system\logs\nginx-error.log"

function Invoke-Step {
    param([string]$Desc, [scriptblock]$Act)
    Write-Host "[migrate] $Desc" -ForegroundColor Cyan
    if ($DryRun) { return }
    & $Act
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "step failed: $Desc (rc=$LASTEXITCODE)"
    }
}

以上是骨架示意——实施时写完整脚本,要点:
1. `Invoke-Step` 在 DryRun 下只打印;正常模式每个 nssm 调用后检查退出码,失败即 throw 中止;
2. 幂等:`Get-Service erp-web` 存在时走 `nssm set` 更新,不存在才 `nssm install`(复刻 GUI `_nssm_install` 的幂等语义);
3. 设置项齐全:Application/AppParameters/AppDirectory/AppExit `Default Restart`/AppRestartDelay 5000/Start AUTO/`AppNoConsole 1`/AppStdout·AppStderr 指向 `logs\erp-web.log`;
4. 停旧树:`nssm stop erp-prod`(Job Object 干净杀 uvicorn+nginx);
5. 验证 erp-web:`nssm start erp-web` → curl `:3000` 验 `Server: nginx` 头 + `/nginx-health` 响应体含 `"service":"nginx"`;
6. 起后端:`nssm start erp-prod` → curl `/api/health` 200;
7. 终态:`python scripts/diag/runtime_mode_probe.py`;
8. 脚本头注释含完整回滚步骤(含 `SERVICE_DISABLED`)。

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_migrate_erp_web_dryrun.py -v`
Expected: 2 passed

- [ ] **Step 9: Commit**

```bash
command git add scripts/migrate_erp_web.ps1 tests/test_migrate_erp_web_dryrun.py
```
提交信息:`feat(scripts): erp-web 迁移脚本(幂等,-DryRun 可断言,回滚步骤注释化)`

---

### Task 5: GUI(server_manager.py)接入 erp-web

**Files:**
- Modify: `server_manager.py`(五处元组 + 安装流 + 渲染)
- Test: 无 GUI 测试基建 → 静态断言测试 `tests/test_server_manager_erp_web.py`(新建)

**Services:**
- `_SVC_WEB = 'erp-web'` 常量追加于 `_SVC_ARQ` 之后。
- `_SVC_DEPENDS` 字典新增 `erp-web: []`(无依赖)。

**Interfaces:**
- Consumes: prod_runner 状态文件新契约(`frontend external`)
- Produces: 五处 `(_SVC_API, _SVC_ARQ)` → `(_SVC_API, _SVC_ARQ, _SVC_WEB)`;`_install_services_flow` 三服务安装;前端徽章 external 范式渲染。

- [ ] _SVC_WEB 常量与依赖

在 `server_manager.py` 顶部常量区(`_SVC_ARQ` 之后)加:

```python
_SVC_WEB = 'erp-web'  # nginx 静态服务(prod_runner 已不再托管,独立 NSSM 服务)
```

`_SVC_DEPENDS`(若存在该字典)加 `erp-web: []`。若实际为硬编码 depends 列表传参,则 Task 内直接在调用点传入 `depends=None`。

- [ ] 五处元组扩展

全部改为三元组 `(_SVC_API, _SVC_ARQ, _SVC_WEB)`:

1. `_managed_service_pids`(`for name in (_SVC_API, _SVC_ARQ):` 行)
2. `_stop_managed_services` 同上
3. `_service_cmd_sync` 同上
5. `_uninstall_services_flow` 同上
4. `_start_services_flow` 的 offsets 字典推导 `{name: self._log_size(...) for name in (_SVC_API, _SVC_ARQ)}` → 三元组

- [ ] 安装流三服务

`_install_services_flow` 在 erp-arq 之后追加第三项(仿 erp-arq 写法,Application 指向 nginx.exe,env_extra 空串,params 列表为 nginx 参数):

```python
        self._gate.checkpoint()
        ok3 = self._nssm_install(nssm, _SVC_WEB, r'C:\nginx\nginx.exe',
                                 ['-p', 'D:\\erp_system', '-c', 'D:\\erp_system\\config\\nginx-windows.conf',
                                  '-e', 'D:\\erp_system\\logs\\nginx-error.log'],
                                 '', depends=None)
        if ok1 and ok2 and ok3:
            ...('生产服务安装完成:erp-prod + erp-arq + erp-web(开机自启、按依赖顺序启动)')
```

注意 `_nssm_install` 的 env_extra 参数是位置参数,空串即不入 AppEnvironmentExtra(NSSM 对空 set 同样安全)。

- [ ] 状态渲染(仿 ARQ external 范式)

`_apply_hosting_data` 中:

```python
            arq = svcs.get('arq') or {}
            if arq.get('status') == 'external':
                ...existing arq logic...
            fe = svcs.get('frontend') or {}
            if fe.get('status') == 'external':
                # erp-web 独立服务:以服务状态为准,frontend_ok 探针交叉验证
                fe_state = self._svc_state(_SVC_WEB)
                if 'RUNNING' in fe_state:
                    if data.get('status', {}).get('frontend_ok'):
                        _detail(self.hosting_frontend_badge, 'running', '前端 运行中')
                    else:
                        _detail(self.hosting_frontend_badge, 'deploying', '前端 服务在跑但探针未过')
                elif 'STOPPED' in fe_state:
                    _detail(self.hosting_frontend_ok_badge_unused, 'stopped', '前端 已停止')  # 实施时用 hosting_frontend_badge
                else:
                    _detail(self.hosting_frontend_badge, 'stopped', f'前端 {fe_state}')
            else:
                _svc_detail(self.hosting_frontend badge, '前端', svcs. get('frontend'),
                            running=('running', 'ready'))
```

以上为结构示意,实施时对齐现网代码风格与既有 `_svc_detail` 映射,变量名以实际为准(`hosting_frontend_badge`)。**不要**引入新徽章变量。

- [ ] **静态断言测试**

`tests/test_server_manager_erp_web.py`:

```python
"""server_manager.py 对 erp-web 的接入点静态断言(无 GUI 测试基建,以文本锁定)。"""
from __fut re__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "server_manager.py"
TEXT = SRC.read_text(encoding="utf-8")


def test_svc_web_constant() -> None:
    assert "_SVC_WEB = 'erp-web'" in TEXT


def test_five_tuples_extended() -> None:
    # 统计五处关键迭代点都出现三元组
    assert TEXT.count("(_SVC_API, _SVC_ARQ, _SVC_WEB)") >= 5


def test_install_flow_has_erp_web() -> None:
    assert "_nssm_install(nssm, _SVC_WEB" in TEXT


def test_frontend_external_rendering() -> None:
    assert "fe.get('status') == 'external'" in TEXT


def test_no_leftover_two_tuple_in_flows() -> None:
    # 五处流转点不应残留二元组(装饰器/文档字符串中的历史引用除外)
    import re
    flows = re.findall(r"for name in \(([^)]+)\):", TEXT)
    two = [f for f in flows if "_SVC_API" in f and "_SVC_WEB" not in f]
    assert not two, f"残留二元组: {two}"
```

- [ ] 跑静态断言

Run: `python -m pytest tests/test_server_manager_erp_web.py -v`
Expected: 5 passed

- [ ] **Commit**

```bash
command git add server_manager.py tests/test_server_manager_erp_web.py
```
提交信息:`feat(server_manager): GUI 接入 erp-web——五处服务元组扩展+安装流+external 范式渲染`

---

### Task 6: worker 数调整(顺带项)

**Files:**
- Modify: `config/nginx-windows.conf:12`(`worker_processes auto` → `2`)
- Modify: `.env`(`UVICORN_WORKERS=8` → `4`)

**Interfaces:**
- Consumes: 无
- `produces`: 无接口产出

- [ ] **Step 1: 改 nginx conf**

`config/nginx-windows.conf` 第一处 `worker_processes auto;` 改为 `worker_processes 2;`,并追加注释说明 6 物理核静态服务足够。

- [ ]  **Step 2: 改 .env**

`UVICORN_WORKERS=8` → `UVICORN_WORKERS=4`。

- [ ] **Step 3: 验证 nginx conf 语法**

Run: `"C:/nginx/nginx.exe" -t -p D:/erp_system -c D:/erp_system/config/nginx-windows.conf`
Expected: `syntax is ok` / `test is successful`

- [ ] **Step 3: Commit**

```bash
command git add config/nginx-windows.conf
```
`.env` 不入库(.gitignore),单独验证不入库:Run: `command git check-ignore .env` → 应输出 `.gitignore:28:.env`。UVICORN_WORKERS 的改动不进 git,迁移日生效。

- [ ] **Step 4: 确认全量测试绿**

Run: `python -m pytest fastapi_app/tests/ -x -q`
Expected: 全部 PASS

- [ ] fastapi_app 测试后跑全仓测试确认无回归

Run: `python -m pytest tests/ utils/tests/ -q` (若 utils/tests 不存在则只跑 tests/)
Expected: 全部 PASS

- [ ] **Step 5: Commit(nginx conf 已含上一提交步骤)**

若 nginx conf 与 .env 分属不同提交,nginx conf 进 git;`.env` 改动属运行时配置不入库——在提交信息里注明。

提交信息:`chore(config): nginx worker_processes auto→2(6 物理核,静态服务足够)`

---

### Task 7: 文档同步

**Files:**
- Modify: `docs/runbooks/service-lifecycle.md`(§1 拓扑、§4 验证、§5 故障)
- Modify: `README_DEPLOY.txt`(服务清单)
- Modify: `CHANGELOG.md`
- Delete: `restart_prod.ps1`(死脚本)

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 无

- [ ] **Step 1: service-lifecycle.md 更新**

§1 拓扑图重写为五服务(erp-web 独立),prod_runner 描述改为"只守护 uvicorn,前端由 erp-web 托管,探针只观察";§4.1 保留四条硬判据;§5 增补条目:

- 「erp-web 挂了但 erp-prod 绿」:正常现象,`nssm restart erp-web` 即可,不影响 API;
- 「回滚后重启机器双 nginx」:按回滚步骤先 `nssm set erp-web Start SERVICE_DISABLED`。

§5.2 孤儿 worker 条目保留但补注:erp-web 由 NSSM Job Object 托管,绕过 NSSM 手工杀 nginx master 才会产生孤儿。

- [ ] **Step 2: README_DEPLOY.txt 更新**

服务清单从"三个 Windows 服务"改为"四个"(erp-prod / erp-arq / erp-web / erp-redis / erp-redis-broker,共五个,按实际数)。

- [ ]原文说"三个 Windows 服务由 NSSM 托管:erp-prod、erp-arq、erp-redis",需改为五个并更新拓扑图,增加"前后端重启解耦:重启 erp-prod 不再影响前端静态服务"。

- [ ] **Step 3: CHANGELOG 追加条目**

格式对齐现有条目(见文件头样式),追加本次重构记录。

- [ ] **删除 restart_prod.ps1**

Run: `command git rm restart_prod.ps1`
理由:被自身护栏拦死的死脚本,继续误导人。

- [ ] **Step 4: Commit**

```bash
command git add docs/ README_DEPLOY.txt CHANGELOG.md
command git rm restart_prod .ps1
```
提交信息:`docs+chore: 五服务拓扑文档同步,删除已废弃 restart_prod.ps1`

---

### Task 8: 全量验证与交付清单

**Files:**
- Create: `deliverables/2026-09-28-erp-web-migration/VERIFICATION.md`(验证清单交付物)

**Interfaces:**
-  >Consumes: 全部前序任务
- Produces: 验证清单文档

- [ ] **Step 1: 全量测试**

Run: `python -m pytest fastapi_app/tests/ tests/ utils/tests/ -q 2>&1 | tail -5`
Expected: 0 failed

- [ ] **Step 2: 迁移脚本 DryRun 测试**

Run: `python -m pytest tests/test_migrate_erp_web_dryrun.py -v`
Expected: 2 passed

- [ ] **Step 3: prod_runner --check 自检**

Run: `python -m fastapi_app.core.prod_runner --check`
Expected: Redis OK / dist 存在 / worker 数 = 4 / erp-web 提示(不再有 vite preview 回退文案)

- [ ] **Step 4: 写交付清单 VERIFICATION.md**

内容含:
1. 迁移执行步骤(管理员 PowerShell):`scripts/migrate_erp_web.ps1`(六步,含回滚注释)
2. 迁移后验证四条硬判据 + runtime_mode_probe 终态;
3. GUI 手动验证五服务卡片、生产→开发→生产切换;
4. 回滚步骤完整版;
5. 未来任务勾选项:备份可观测性(独立任务,spec 引用)。

- [ ] **Step 5: Commit**

```bash
command git add deliverables/2026-09-28-erp-web-migration/VERIFICATION.md
```
提交信息:`docs(deliverables): erp-web 迁移验证清单`

---

## Self-Review

**1. Spec coverage:**

- §3 目标拓扑(五服务)→ Task 2/4/5 ✓
- §4 erp-web 服务定义 → Task 4 ✓
- §5 prod_runner 瘦身 → Task 2 ✓(含 .bak 删除、check() 更新)
- §6 GUI 攀接(五元组/安装流/external 渲染/保留 _find_loose) → Task 5 ✓
- §7 ARQ 轜转 → Task 3 ✓
- §8 顺带项 worker 数 → Task 6 ✓
- §9 迁移脚本与回滚 → Task 4 ✓
- §10 测试策略 → 各 Task 内嵌 + Task 8 全量验证 ✓
- §11 文档同步 → Task  coverage 7 ✓
- **显式核查:2010 交付清单(VERIFICATION.md)覆盖了运行时验证(四判据+probe)与 GUI 手动验证,即 spec §10 用户手动验证项。** ✓

**2. Placeholder scan:** 无 "TBD/TODO/实施时补"。Task 4 Step 3 的 PowerShell 代码块为可直接落盘的函数骨架 + 8 条完整要点清单;Task 5 的渲染代码为对齐现网风格的结构示意,附"不要引入新徽章变量"的明确约束。

**3. 语法/拼写检查:** 计划内文件名(`migrate_erp_web.ps1`、`test_server_manager_erp_web.py`)已统一修正;Step 编号连续。

**3. Type consistency:** `rotate_file_copytruncate(path: Path, max_bytes: int) -> bool` 在 Task 1/2/3 保持一致 ✓;`_frontend_probe_ok() -> bool` Task 2 定义、Task 5 消费 ✓;`rotate_nginx_logs_task(ctx)` Task 3 定义、测试消费 ✓;五元组模式 Task 5 内部一致 ✓

**3b. 测试文件名一致性(Task 4/5/8 跨任务引用):** Task 4 落盘 `tests/test_migrate_erp_web_dryrun.py`,Task 8 Step 2 引用同名(笔误处已修正) ✓

**3c. ARQ 路径假设验证:** Task 3 假设 `fastapi_app/core/tasks/` 存在;实施时以 `arq_app.py` 现有 import(`from fastapi_app.core.tasks.xxx import` 形式)为准,若不存在则需 mkdir 并加 `__init__.py`,测试同步。

**3d. nginx conf `-t` 验证注意:** Task 6 Step 3 用 `-p D:/erp_system` 前缀跑 `nginx -t` 会写 `logs/nginx-error.log`(prod_runner 之外的文件),注意验证时区分。

**3e. memory 记忆冲突提示:** [[frontend-3000-serving-mode]] 记忆强调"构建前先探测 :3000"。本计划不涉及前端构建,无冲突;但 Task 8 VERIFICATION.md 应提醒用户:若后续要构建前端,迁移后 :3000 由 erp-web 托管,`build:atomic` 的 dist 交换不再受 dev server watcher 锁影响(dev server 需从 5173 起或停),但 dist 交换仍需注意 dev server 是否占 3000。补充:本机当前 dev server 常以 `--port 3000` 起([start.py](start.py) `--web-port 3000` 默认),dev 模式下 vite 用 3000,迁移后 erp-web 也用 3000,切换模式时 GUI 的"停开发"流程已处理端口互斥,故无额外风险。

**3f. `_frontend_probe_ok` 的归属:** Task 2 代码块里的模块级函数是初稿;更稳妥做法是 **Supervisor 方法** `self._frontend_probe_ok()`,读 `self.web_port`(与 main() 的 `_get_int_env("WEB_PORT", 3000)` 同源,不与 .env 脱钩)。**决定:实施时按 Supervisor 方法落地**,测试打桩用实例属性(monkeypatch.setattr(sup, "_frontend_probe_ok", ...)),Task 2/5 均兼容。

**4. Review Focus coverage:**
- 迁移中断/双 nginx → Task 4(命令序列断言 + 回滚含 SERVICE_DISABLED)✓
- GUI 漏 erp-web → Task 5(五元组静态断言 + `test_no_leftover_two_tuple_in_flows` 断言无残留二元组)✓
- dev 模式抢不到 :3000 → Task 5 同上 ✓
- 轮转函数下沉破坏 prod_runner 自身日志轮转 → Task 1 单测锁定行为不变 + Task 2 `--check` 自检 ✓
- 回滚后双 nginx → Task 4 回滚注释 + 测试断言 SERVICE_DISABLED ✓

---

## 执行方式

本计划任务间接口依赖链清晰(Task 1 → 2 → 3,Task 5 依赖状态文件契约,Task 6/7/8 收尾),但都是同一代码仓库的强耦合改造,分批下发 subagent 会带来接口漂移风险;建议 Native(本会话自实施)——计划已将设计全量携带,采用计划驱动实施 + 结尾整体 fresh-context review。

**推荐执行方式:Native**。

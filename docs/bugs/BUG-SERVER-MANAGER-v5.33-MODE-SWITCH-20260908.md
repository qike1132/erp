# BUG 报告：服务器管理器 v5.33 开发模式无法开启 / 生产模式无法停止

- **日期**: 2026-09-08
- **影响版本**: `dist/ERP服务器管理器_v5.33.exe`（构建于 2026-08-15 21:47）
- **现象**: ① 点击「启动开发模式」必失败；② 「生产模式」点击停止后状态仍为运行中
- **结论**: 根因 1 已在当前源码（v6.0.0, 2026-08-22 后）修复，**但 exe 从未重新打包**；根因 2 在当前源码中仍未修复，需代码加固。

---

## 一、证据（logs/server_manager_20260908.log）

```
22:01:14  正在启动开发模式（前后端）...
22:01:14  正在停止生产服务 erp-prod...
22:02:00  ERROR: 启动流程异常: not enough values to unpack (expected 3, got 2)   ← 间隔 45.6s ≈ _wait_service_stopped 超时(45s)
22:02:00  ERROR: 开发模式（前后端）启动失败: not enough values to unpack (expected 3, got 2)
22:13:42  （第二次尝试，同样 45s 后同样错误）
22:12:51 / 22:13:09 / 22:13:29×4  erp-prod stop 已执行（但服务始终未停）
22:01:07  一秒内 6 条「正在执行停止/重置操作」← 按钮无防重入，多轮清理线程并发
22:01:07  已终止端口6379占用进程 + 发现 7 个残留进程正在终止 ← python/uvicorn/node 宽特征扫描
```

## 二、根因 1：开发模式无法开启 —— v5.33 exe 内置解包 bug（版本错位）

**commit `653f505`（2026-08-15 16:51，exe 构建 5 小时前）的 server_manager.py：**

- 调用方（L1106）：`ok, reason, stopped_any = self._ensure_production_stopped()` → 解包 **3** 元组
- 停止超时分支（L1575）：`return False, f'{name} 停止超时（STOP_PENDING 未确认），已中止切换'` → 只返回 **2** 元组

**触发链条**：点「启动开发模式」→ 互斥托管先停生产 → `erp-prod` 45 秒内未确认 STOPPED → 走超时分支返回 2 元组 → 调用方解包崩溃 → `dual_failed` 回滚。**只要生产服务停不下来，开发模式 100% 启动失败。**

**版本考古**：

| 版本 | 时间 | 超时分支返回值 | 调用方解包 | 状态 |
|---|---|---|---|---|
| 653f505（v5.33 exe 所用） | 08-15 16:51 | 2 元组 | 3 元组 | ❌ 必崩 |
| server_manager.py.bak-20260822 | 08-22 13:50 | 3 元组 | 3 元组 | ✅ 已修 |
| 当前源码 (_VERSION='v6.0.0') | 08-26 18:37 | 3 元组（L4520） | 3 元组（L3986） | ✅ 已修 |

spec 输出名已是 `ERP服务器管理器_v6.0.0`，但 dist 里仍只有 08-15 的 v5.33 exe —— **修复未发版**。

## 三、根因 2：生产模式无法停止 —— 三层机制叠加

1. **「停止」无确认即报成功**：`_service_cmd_sync`（L4748-4759）发出 `nssm stop`（无 nssm 时回落 `sc stop`）后**不等待 STOPPED 确认**，无论 returncode 一律打「erp-prod stop 已执行」；`except: pass` 吞掉「拒绝访问」等真实失败。随后 `hosting_refresh` 立即刷新，服务仍 RUNNING/STOP_PENDING → UI 表现为「停不掉」。
2. **AppExit 自动复活**：`_nssm_install` 设置 `AppExit=Default Restart` + `AppRestartDelay=5000`（L4696-4697）。而「停止/重置」的 `_kill_residual_async`（L4246-4267）按 `python`/`uvicorn`/`node` 宽特征扫描强杀——**必然误杀 NSSM 监管中的 erp-prod/erp-arq 工作进程**（它们就是 `python -m prod_runner`）→ NSSM 判定崩溃 → 5 秒后自动重启 → 「杀不死/停了又起」。源码注释（L4474）自证此坑。
3. **权限因素（待现场确认）**：`nssm stop`/`sc stop` 需要管理员权限；`server_manager.spec` **未配置 `uac_admin`**（默认 asInvoker），若 exe 未右键管理员运行，stop 指令被拒且被静默吞掉。

循环闭环：残留清理误杀 → NSSM 5 秒重启 → 手动 stop 无确认仍显示运行 → 点开发模式 → 45s 停不等不到 STOPPED → 旧 exe 解包崩溃 → 开发模式失败。

## 四、环境因素排查清单

| 项 | 排查方法 | 判定 |
|---|---|---|
| 是否管理员运行 | 任务管理器「已提升」列 / 右键 exe 属性 | 非管理员则服务控制全被拒 |
| NSSM 可用性 | `where nssm`；config 的 `nssm_path` | 找不到则回落 `sc stop`（更依赖提权） |
| 服务实际状态 | 管理员终端 `sc query erp-prod`、`sc queryex erp-arq` | STATE 与 PID；对照 GUI 显示 |
| 服务进程日志 | `logs/erp-prod.log` 是否每 ~5s 一轮重启痕迹 | 有则证实 AppExit 复活 |
| exe 与源码版本 | exe 构建时间 vs `_VERSION` | v5.33(08-15) ≠ v6.0.0(08-26) |
| GUI 错误提示 | 日志 `unpack (expected 3, got 2)` | GUI 自身 bug，非环境问题 |

## 五、修复方案

### 立即恢复（不改代码）
1. **管理员终端手工停服**：`nssm stop erp-prod && nssm stop erp-arq`，`sc query` 确认双 STOPPED 后再点开发模式（旧 exe 若生产已停则不会走超时分支，可启动成功——但根治仍需重打包）。
2. **重新打包**：`pyinstaller server_manager.spec` → 产出 `ERP服务器管理器_v6.0.0.exe`，替换 v5.33。**重打包即可根治根因 1**（L3986/L4520 已一致返回 3 元组）。

### 代码加固（根因 2，当前源码仍未修）
1. `_service_cmd_sync`：检查 returncode；stop 后复用 `_wait_service_stopped` 等 STOPPED 确认；失败时把真实原因（拒绝访问/超时）写入日志与 toast，替换无条件「已执行」。
2. `_kill_residual_async`：先 `nssm stop` 并确认 STOPPED，再清残留；扫描特征排除 `prod_runner`/服务 PID 树（现仅 `_ensure_production_stopped` 排除了 prod_runner，`stop_all` 路径没有）。
3. AppExit：stop 前临时 `nssm set <name> AppExit Default Exit`（或改 `AppThrottle`/停用自动重启），stop 确认后恢复，杜绝 5 秒复活。
4. `stop_all` 加防重入守卫（'stopping' 状态），日志证实连点导致 6 轮并发清理。
5. spec 增加 `uac_admin=True`，或启动时检测提权并明确提示，避免静默 Access Denied。

### 预防
- 发版纪律：源码修复后立即重打包并核对 exe 构建时间与 `_VERSION` 一致。
- 返回值契约：跨函数元组返回值增删时同步全部调用点（本次即 2→3 元组迁移漏改一处分支）。

## 六、具体操作步骤

1. 关闭 v5.33 exe（含托盘）。
2. 管理员 PowerShell：`nssm stop erp-prod; nssm stop erp-arq`，`sc query erp-prod` 确认 STOPPED。
3. 项目根目录执行 `pyinstaller server_manager.spec`，将 `dist/ERP服务器管理器_v6.0.0.exe` 复制为常用启动位置，后续一律以管理员运行。
4. 验证：① 生产运行中直接点「启动开发模式」→ 应自动停生产并完成 5 步启动；② 开发运行中点「启动生产」→ 自动停开发；③ 生产模式下点「关闭」→ 60s 内状态变为已停止。
5. 若第 4 步生产停止仍超时，检查 `logs/erp-prod.log` 重启痕迹并执行第五节代码加固第 1-3 条。

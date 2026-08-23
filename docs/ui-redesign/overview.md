# ERP 服务器管理器 UI 重构 — 项目状态总览

> 更新：2026-08-22 14:05 · 路线 A（Tkinter 渐进对齐 v2）进行中

## 当前状态

| 项 | 状态 |
| --- | --- |
| `server_manager.py` | **v6.0.0**（三段式 UI 已落地；通用一键操作组件已接线；默认主题已切亮色） |
| `dist/ERP服务器管理器_v5.33.exe` | 旧包，等待 v6.0.0 重新打包覆盖 |
| 设计交付物 | `docs/ui-redesign/` 下：方案文档、v2 设计决策说明、一键操作实现方案、通用组件、原型 |

## 已完成清单
1. **UI 重构方案**（v1 设计文档 + v2 设计决策说明）
2. **高保真原型**：`ui_prototype_v2.html`（组件化：ActionLock→Controller→OneClickPanel，dev/prod 共用）
3. **通用一键操作组件**：`D:\erp_system\one_click_action.py`（Python 版，6 项逻辑回归通过）
4. **组件接线**：dev/prod 双 spec + 共享 ActionLock；`_stop_dual_mode_sync`/`_prod_restart_sync`/`_prod_stop_sync`/`_wait_service_running`
5. **亮色默认**：`_APP_CONFIG_DEFAULTS['theme']='light'` + 配置文件同步（v6.0.0 LIGHT 色板 ≈ v2 Token）
6. **服务管理页双操作卡**：开发卡（启动/重启/关闭/环境徽章/启动进度条）+ 生产卡（同构 + 服务明细）

## 关键发现（排查"还是老UI"）
- `ui_prototype_v2.html` 是设计稿（HTML），`server_manager.py` 是 Tkinter 桌面程序——载体不同，改设计稿≠桌面界面
- v6.0.0 各页面（Overview/Logs/Services）本就按 v2 设计实现，老 UI 根源是 **dark 主题锁在配置里**，切 light 即大厂风

## 待办
- [ ] 打包完成：`dist/ERP服务器管理器_v6.0.0.exe`（后台任务 RqE6QP）
- [ ] 用户实机验证亮色 + 双操作卡
- [ ] 可选 P3：其余页细节微调、暗色主题再打磨

## 参考文件
- 方案：`ERP服务器管理器UI重构设计方案.md` / `UI重构V2设计决策说明.md`
- 组件：`通用一键操作组件设计.md` + `one_click_action_component.py`（docs 版）/ `one_click_action.py`（已接线版）
- 实现方案：`一键操作按钮功能实现方案.md`
- 原型：`ui_prototype_v2.html`

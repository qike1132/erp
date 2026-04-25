# BUG-UI-STOP-STATE 修复记录

- **修复时间**: 2026-04-23
- **Git Commit**: 215ee3c246501153bdfaa3313b3e5a71aa03a7c1
- **根因分析**: `_stop_mode()` 和 `stop_all()` 在设置 `self._mode = 'none'` 后未立即调用 `_update_all_ui()`。UI 更新依赖 `_kill_worker` 后台线程完成后的 `('ui_update', {})` 队列消息，该消息延迟可达数秒（taskkill 超时10s + proc.wait 3s）。在此期间 UI 仍显示"运行中"。
- **影响范围**: 所有用户点击停止按钮的场景（停止调试/停止生产/停止所有）
- **修复方案**: 在 `_stop_mode()` (line 904) 和 `stop_all()` (line 913) 中，`self._mode = 'none'` 之后立即调用 `self._update_all_ui()`，使 UI 即时反映停止状态
- **验证结果**: L1~L5 全部通过, bandit 0 HIGH, 语法检查通过, exe 重建成功 (17.85 MB)
- **健康端点**: N/A (GUI 应用)

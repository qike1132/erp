---
intent: 在 ERP 服务器管理器 GUI 中，开发/生产启动时自动关闭对方模式并清理端口，实现互斥无缝切换
success_criteria:
  - 点击开发启动：若生产 NSSM 服务运行 → 自动等待停止 erp-prod+erp-arq、清理残留 prod_runner、释放 5002/3000，开发模式正常启动
  - 点击生产启动：若开发模式运行 → 停止开发进程、释放 5002/3000，erp-prod+erp-arq 正常启动
  - 切换全程 Redis 6379/6380 不动；开发 starting/restarting 时生产启动被拒绝
risk_level: medium
auto_approve: false
---

## Steps

- [ ] **Step 1: 复核 server_manager.py 关键方法现状**
action: Read server_manager.py 中 _stop_dual_mode_async、_kill_process_tree、_kill_port_sync、_find_port_pids、_svc_state、_service_cmd、_start_dual_server、_start_services 的实现，确认可复用函数签名与现有线程/消息队列模式（self._msg_queue、self._mode、self._current_mode_key），不做任何修改。
verify:
  - type: shell
    command: python -c "import ast,sys; ast.parse(open('server_manager.py',encoding='utf-8').read()); print('syntax ok')"
gate: auto

- [ ] **Step 2: 新增 _wait_service_stopped 与 _ensure_production_stopped**
action: 在 server_manager.py 的 _svc_pid 方法附近新增两个方法：1) _wait_service_stopped(self, name, timeout=45)：调用 nssm stop name，随后循环调用 _svc_state(name) 直到状态含 STOPPED 或超时，超时返回 False；2) _ensure_production_stopped(self)：读 _SVC_API/_SVC_ARQ 状态，对运行中的服务逐个 _wait_service_stopped，任一超时则返回 (False, '服务名')；随后用 subprocess 执行 wmic/powershell 列出命令行含 prod_runner 的 python 进程，对每个 PID 用 _kill_process_tree 清理；全部成功返回 (True, None)。此方法不触碰 Redis。
verify:
  - type: shell
    command: python -c "import re; s=open('server_manager.py',encoding='utf-8').read(); assert '_wait_service_stopped' in s and '_ensure_production_stopped' in s; print('methods added')"
gate: auto

- [ ] **Step 3: 新增 _ensure_development_stopped 与 _release_ports**
action: 1) 新增 _ensure_development_stopped(self)：若 self._mode 为 dual_dev 或 self._process/self._frontend_process 存在，复用 _stop_dual_mode_async 的进程清清理逻辑（遍历 self._process 与 self._frontend_process，非 poll() 则 _kill_process_tree），随后将 self._mode=None、self._current_mode_key=''，并通过 self._msg_queue 发 ('hosting_refresh',{}) 与 ('status',{'text':'已停止开发模式'})；只在工作线程内调用，不得直接改控件。2) 新增 _release_ports(self)：调用 self._kill_port_sync(_API_PORT) 与 self._kill_port_sync(_WEB_PORT)。
verify:
  - type: shell
    command: python -c "s=open('server_manager.py',encoding='utf-8').read(); assert '_ensure_development_stopped' in s and '_release_ports' in s; print('methods added')"
gate: auto

- [ ] **Step 4: 改造 _start_dual_server 前置互斥切换**
action: 修改 _start_dual_server：在现有 'self._mode != none' 拒绝检查保留的基础上，改为——若 self._mode in ('starting','restarting') 直接 return 并日志提示；否则先调用 _ensure_production_stopped()，若返回 (False, name) 则日志 ERROR 并 return（fail-closed，不启动开发）；若返回 (True, None) 且确有生产运行，日志提示「已自动停止生产模式」；随后调用 self._release_ports()，再继续原有启动流程（_start_dual_thread 内部对 5002/3000 的清理可保留）。确保整段在调用线程（按钮回调）内执行，不启动新线程。
verify:
  - type: shell
    command: python -c "s=open('server_manager.py',encoding='utf-8').read(); assert '_ensure_production_stopped()' in s; print('dual guarded')"
gate: auto

- [ ] **Step 5: 改造 _start_services 前置互斥切换**
action: 修改 _start_services：先判断 self._mode，若 in ('starting','restarting') 则日志 WARNING「开发模式正在启动中，请稍候」并 return（防 TOCTOU）；否则调用 self._ensure_development_stopped()，若开发进程曾被停止则日志提示「已自动停止开发模式」；随后调用 self._release_ports()；最后再调用原 self._service_cmd('start')。保留 _stop_services/_restart_services 原样。
verify:
  - type: shell
    command: python -c "s=open('server_manager.py',encoding='utf-8').read(); assert '_ensure_development_stopped()' in s or '_ensure_development_stopped' in s; print('prod guarded')"
gate: auto

- [ ] **Step 6: 语法与导入校验**
action: 运行 python -m py_compile server_manager.py 与 python -c "import server_manager"，确认无语法错误、无导入冲突、无未定义引用（尤其新增方法引用的 _kill_process_tree/_svc_state/_msg_queue 均存在）。
verify:
  - type: shell
    command: python -m py_compile server_manager.py
gate: auto

- [ ] **Step 7: 静态自检新增方法引用一致性**
action: 用 Grep 检查新增 4 个方法（_wait_service_stopped/_ensure_production_stopped/_ensure_development_stopped/_release_ports）在 server_manager.py 中定义与调用点，确认：无重复定义、方法名拼写一致、引用的模块级常量（_SVC_API/_SVC_ARQ/_API_PORT/_WEB_PORT）与辅助函数（_kill_process_tree/_svc_state/_kill_port_sync）均已在本文件定义。若有缺失引用立即修复。
verify:
  - type: shell
    command: python -c "s=open('server_manager.py',encoding='utf-8').read(); needs=['_wait_service_stopped','_ensure_production_stopped','_ensure_development_stopped','_release_ports','_kill_process_tree','_svc_state','_kill_port_sync','_SVC_API','_SVC_ARQ','_API_PORT','_WEB_PORT']; assert all(n in s for n in needs); print('refs ok, count=%d'%len([n for n in needs]))"
gate: auto

- [ ] **Step 8: 人工 GUI 双向切换验证**
action: 由用户实际操作 GUI 验证：A) 先启动生产服务，再点开发启动，日志应出现「已自动停止生产模式」，随后开发模式就绪，5002 归 uvicorn、3000 归 vite；B) 开发运行中点启动服务，开发进程停止、5002/3000 空闲、erp-prod/erp-arq RUNNING、3000 归 nginx；C) 切换全程 Redis 6379/6380 可 PING；D) 开发 starting 时点启动服务被拒绝并提示。
verify:
  - type: human-review
    check: 用户确认 A/B/C/D 四项均符合预期，无端口冲突、无双后端、Redis 未被动
gate: human
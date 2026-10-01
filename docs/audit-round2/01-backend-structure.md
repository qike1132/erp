# 01 · 后端结构与分层审计（t1 完整报告）

> **本文件元信息**（由 docs-archivist 于归档时统一添加，正文未改）
>
- **审计轮次**：2026-10-01 第二轮全面审计（binfa-ERP / D:\erp_system）
- **基线**：aac4c43f59a4374e05cdc5aee6c4aaa8afc99026（2026-10-01 14:52:03，成员取证时的 HEAD）
- **归档 HEAD**：546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43，chore(types): mypy 覆盖 106→110（OPT-13 第一批），顺带删 staging_utils 死代码）
- **来源**：成员报告 `t1-backend.report.md（23,904 B）`（恢复件 23,904 B / 17,038 字符）
- **恢复方式**：captain 从 t1 成员会话转录恢复原报告全文，本文件逐字归档；仅把【…】/━━━ 分节符规范为 Markdown 二级标题，正文与 文件:行 未改。
- **完整性**：记为「完整」；恢复件 128 行，四个分节 + 可复现命令清单 + 文末一句话结论齐全，未观察到截断。注意：成员产出时写入任务 output 的原始版本未随本目录保存（团队状态目录曾丢失），本文件是转录件。
- **只读声明**：全程只读静态审计：不改代码/配置/数据库，不重启服务、不装依赖、不发起任何攻击性请求；临时脚本仅写 %TEMP%\erp_audit_v2\。本文件是审计产物的**归档副本**，正文结论与 文件:行 证据保持成员原文。
- **归档时间**：2026-10-01（第二轮审计当日）

【硬性提醒】所有 文件:行 均相对基线 aac4c43f 取证；归档时仓库 HEAD = 546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43）已在其上新增 1 个提交（mypy 覆盖 106→110、顺带删 staging_utils 死代码），行号可能已漂移，引用前请重新核对。

**归档者独立复核（本轮实测，非成员转述）**：抽查 `fastapi_app/core/exceptions.py:203-214`（db_transaction 把 NotFoundError/AppError 转 HTTPException → 业务错误码失效）、`:74` make_error_response 死 helper、`fastapi_app/core/database.py:203` get_async_db（:229 commit、:231 commit 失败仅 logger.error）、`:333` get_async_read_db（:352 asyncio.timeout(2.0s) 降级主库、:364 finally close）、`fastapi_app/api/v1/endpoints/numbering_audit.py:19-26` 端点内直接 `db.execute(select(...))`、`fastapi_app/api/v1/endpoints/backup/records.py:90` delete_server_backup —— 全部逐字命中。**未复核**：1209 模块 / 2674 边的依赖图与 9 个 SCC（需跑成员的 ast 脚本 graph2.py/scc2.py，本轮未跑）。

---
## t1 后端结构与分层审计 · 最终报告
只读审计；ast 全量解析 560 个 .py（fastapi_app 537 + server_manager 13 + utils 9 + server_manager.py），parse_fail=0、unresolved-internal=0；临时脚本全部在 %TEMP%\erp_audit_v2\，未触碰仓库。所有结论均可复现（命令见文末）。

## 一、总体判断
1) 分层真实存在、不是泥球：实际链路 api.endpoints → services → shared_models（ORM 模型兼数据层），core 是两侧共用的基础设施内核，schemas 只服务 api 侧响应模型；越层小口子共 6 处（core→services 3、services→schemas 8、shared_models→core 2、utils→shared_models 3）。
2) 但不是最优，4 个结构性缺口：
   ① 没有仓储/CRUD 层：数据访问直接写在 services（184 文件）里，ORM 模型放在 shared_models（46 文件）并被 api 当响应类型引用（api→shared_models 40 条边）；
   ② core/ 膨胀为万能内核（被内部导入 591 次，全仓最大入度来源之一），且已有反向边 core→services（core/arq_app.py:49-76 直接 import 11 个任务函数）；
   ③ services/ 只域化一半：184 文件中 78 个（42%）平铺在 services 根；
   ④ 仓库内并存冻结副本树 backups/material-calculator-rollback-20260911/ 与两份同名工具函数，污染门禁/统计/搜索。
3) 端点层不是主要问题：373 路由中 48 纯透传、289 编排、36 不碰 services（全是控制面）；直接写 ORM/SQL 的路由仅 4 个。真正技术债在"错误与事务契约双轨 + 样板重复"。

## 二、七问逐条
① 分层与依赖方向（模块级图：1209 模块 / 2674 边）
- 层间边（count≥5 全量）：services→services 282、api.endpoints→core 188、services→core 153、shared_models→shared_models 128、services.backup→services.backup 125、tests→services 121、services→shared_models 120、tests→core 120、api.endpoints→services 87、tests→services.backup 69、tests→shared_models 63、core→core 58、tests→api.endpoints 44、api.endpoints→shared_models 40、api.endpoints→schemas 39、services.backup→core 35、api(other)→api.endpoints 34（router.py 挂载）、api.endpoints→api.endpoints 27、server_manager→server_manager 20、services→shared 17、services→utils 16、services.backup→shared_models 16、APP_ROOT→core 15、api.endpoints→services.backup 15、tasks→core 12、tasks→services.backup 9、services→schemas 8、core→tasks 6。
- 入/出度：core out74/in591、shared_models out130/in385、services out602/in501、api.endpoints out402/in105、services.backup out176/in221。→ 端点第一耦合对象是 core(188, 47%) 而非 services(87, 22%)：说明端点被"权限+DB会话+响应封装"驱动，业务调用只是次要出口，这正是"缺仓储层 + core 万能"的另一面。
- 反向依赖完整清单：core→services 2（core/arq_app.py→services.numbering_reconcile、core/event_bus.py→services.notification_service）+ core→services.backup 1（core/health.py→services.backup.freshness）；services→schemas 8（全 dashboard 域：dashboard_service、dashboard/{activities,customer,mobile,nav,todos}、batch_import_parser、batch_import_service）；shared_models→core 2（daily_production_record.py、material_registration.py→core.float_utils）；utils(root)→shared_models 2；utils→shared_models 1。
- 导入环（Tarjan，9 个 SCC，规模 [45,18,6,6,4,3,2,2,2]）与样例路径：
  45：fastapi_app.shared_models.order_batch_audit → fastapi_app.shared_models → 回自身（包 __init__ 聚合 44 子模块）
  18：fastapi_app.services.backup.adapters → fastapi_app.services.backup.restore → 回 adapters（含包根与 orchestration/*）
  6：fastapi_app.services.outsource._queries → services.order_crud → services.order.commands → services.outsource_service → 回 _queries
  6：server_manager.dev_mode → server_manager(包根) → server_manager.app → 回 dev_mode
  4：services.stock_in_service ↔ services.stock_service（含 stock_out_service、stock_return_service）
  3：services.product_search_service ↔ services.product_service（含 bom_service）
  2：core.audit_middleware ↔ core.deps；2：tasks.backup_tasks ↔ core.arq_app；2：services.batch_import_service ↔ services.batch_service
  → 前三个（45/18/6-server_manager）由包 __init__ 聚合驱动，改 import 形态可消；后六个是真实双向依赖。
- 影响：真实环造成"改 A 影响 B"的隐性约束与单测隔离困难；包聚合环让"导入 shared_models 包"与"导入其 44 个子模块"互相牵制。
- 建议：a) 三个包 __init__ 去聚合（只留 docstring/版本，子模块间用绝对模块导入）成本 M（机械可脚本化）；b) outsource/order 环抽纯数据访问或改事件，成本 L；c) stock_* 四服务抽共享基类，成本 M；d) core 不再 import tasks（任务注册改名字表/入口注入），成本 S。

② endpoints 是否过胖 / 业务逻辑是否泄漏
- 实测体积（任务给的旧字节数作废）：purchase_plan.py 30325B/620L/23 路由、backup/validation.py 38126B/858L/6、backup/restore.py 35600B/692L/7、purchase_center/order_routes.py 27935B/669L/19、backup/export.py 26830B/650L/7、order.py 22245B/494L/13、auth.py 22056B/539L/7、outsource.py 20968B/495L/25、customer_sampling.py 19507B/489L/22、case_endpoint.py 19488B/495L/18；api/ 合计 55 文件/634293B/373 路由。
- 行构成揭示"文件大但逻辑薄"：purchase_plan.py 620 = imports 41 + docstring 310 + decorator 23 + comment 5 + blank 103 + 代码 204；order_routes.py 669 = 34/281/19/19/102/268；case_endpoint.py 495 = 33/253/18/0/99/148（docstring 占 41%~51%）。
- 泄漏证据：373 路由中直接调用 select/execute/db.add 的仅 4 个——numbering_audit.py:20 latest_audit、backup/restore.py:442 async_import_backup、:492 async_restore_server_backup、backup/records.py:90 delete_server_backup；raw SQL 字符串 0 处；api/ 内 shared_models 引用 42 处（40 处包级类型导入）。
- 薄厚分类：纯透传 48（batch.py:62-176 七个 import_*_service、case_endpoint.py:64/83/116 等）、编排 289、不碰 services 36（auth.py:87/128/274、dead_letter.py:91/110/147/169、auxiliary.py:125/134、monitoring.py:207 等）。
- 结论：不存在业务逻辑泄漏进端点层；"胖"是可读性与样板问题。真正违规的只有 6 个 body>80 行路由：backup/validation.py:377 validate_backup_file 201L、:584 validate_backup_integrity 160L、:750 get_backup_statistics 108L、auth.py:373 api_refresh_token 107L、backup/export.py:523 export_backup_chunk 95L、backup/restore.py:281 restore_server_backup 90L（违反 quality_gate max_function_length=80）。
- 建议：a) 端点 docstring 压到 1/3，成本 S；b) 权限依赖聚合（见④），S；c) 6 个超长路由抽 helper——validation.py:377/584 的文件校验逻辑应属 services/backup 而非端点，成本 M。

③ 路由注册 / 版本管理 / 响应模型 / 错误处理一致性
- 注册：381 个路由装饰器全部 async（0 sync）。fastapi_app/api/v1/router.py 324 行、34 include_router，34/34 有 prefix、34/34 有 tags、32/34 挂 dependencies=[Depends(get_current_user_id)]（认证统一在挂载层，优）；main.py:393 只挂 v1，无多版本并存；main.py:292/299/388 三个 middleware。
- 响应模型：334/381 有 response_model，47 个缺失（order_routes 7、core/health.py 7、notification 5、backup/export 4、customer_routes 4，余 1-2），多为下载流/health；0 个 responses=、0 个路由级 dependencies=、仅 36 个 summary=。
- 错误处理（最不一致处）：313 处直接 raise HTTPException（top：backup/restore.py 41、purchase_plan.py 31、auth.py 16、backup/export.py 14、daily_production.py 14、order_routes.py 14、tasks.py 13、order.py 12、material_registration.py 11、core/deps.py 9）；JSONResponse 直接构造 0 处（统一 MsgspecResponse，优）。
- 42 个自定义异常类中只有 6 个继承 AppError（core/exceptions.py:18/28/35/42/49/56/63），其余 36 个继承 Exception/ValueError/RuntimeError 全部绕过 app_error_handler；备份域自成 BackupError 家族（services/backup/exceptions.py:5 BackupError 21 次、:25 RestoreError 19 次、:9 BackupLockError 7 次；core/backup_encryption.py:30 BackupFileError 23 次；services/backup/format_strategy.py:45 14 次），必须端点逐个 try/except 转 HTTP。
- 信封不一致：app_error_handler（main.py:302-319）输出 {success,detail,code,status_code,request_id,timestamp}；http_exception_handler（main.py:332-341）无 code 字段 → 业务错误有 code、HTTP 错误无 code，前端无法统一分支。
- 关键因果链：core/exceptions.py:203-214 把 NotFoundError/AppError 转成 HTTPException，因此服务层 AppError 永远到不了 main.py:302 的 handler → 业务错误码体系事实上失效（只有端点直接 raise AppError 才生效）。
- 死代码：core/exceptions.py:74 make_error_response / :126 http_error / :147 app_error_to_http，全仓仅 8 处命中（自身 6 + tests/test_p2_integration.py:31,40），生产 0 使用；其信封为嵌套 {success:False,error:{...}}，与生效的扁平信封互斥 → 两套错误契约并存。
- 建议：a) db_transaction 不再降级 AppError（:203-208 直接 re-raise，仅 error_map 命中转 HTTP），S；b) http_exception_handler 补 code（HTTP_{status}），S；c) 删除三个死 helper 或让全局 handler 复用它们，S；d) 备份域 BackupError 家族加 AppError 适配基类，M。

④ Depends 实际用法与重复
- 747 个 Depends 调用点、47 个文件；目标分布：get_async_db 151、get_async_read_db 113、get_current_user_id 52、get_db 45、get_read_db 31，其余为 require_permission/require_any_permission/require_superuser 家族。
- 事实纠正：get_db / get_read_db 不是遗留同步栈，而是别名（core/database.py:203/333；from fastapi_app.core.database import get_async_db as get_db 命中 9 文件，get_async_read_db as get_read_db 命中 7 文件）→ 同一对象、命名不统一。真遗留仅为 SyncSessionLocal/get_sync_db/sync_engine（core/database.py:456/465/474 自标废弃）。
- 读写库口径清晰：385 路由中 144 只注只读库、191 只注写库、两者同现 0 次、73 个不注 DB。
- 重复样板（单文件重复同一目标）：router.py get_current_user_id ×31（挂载层 32/34 已统一注入，属重复声明）、purchase_center/order_routes.py require_any_permission('product_manage','purchase_center_manage') ×19、case_endpoint.py require_permission('case_manage') ×18、outsource.py get_async_db ×16、material_registration.py ×15、customer_sampling.py get_db ×13 + require_permission(PERM) ×13、purchase_plan.py require_permission('production_plan_manage') ×13 + get_async_read_db ×12。
- 建议：a) 统一 get_db→get_async_db 命名（机械），S；b) 权限按域聚合为单一 Depends，S~M；c) 去掉 router 挂载层之外的重复认证声明，S。

⑤ 事务边界与 session 生命周期
- core/database.py:203 get_async_db 为请求级 UoW，docstring 明示"服务层应使用 flush() 而非 commit()"；:229 响应发送后 commit，**:231 commit 失败仅 logger.error** → 客户端已收 200 但数据未落库（代码自述为已知问题）。:247 get_async_db_context 供 ARQ；:333 get_async_read_db 走只读副本，:352 asyncio.timeout(2.0s) 失败即降级主库，:364 finally close。
- 双轨：131 处 async with db_transaction(db)（另 commit=False 3、error_map 8）＋ 34 处服务/任务自行 commit（23 文件）。缓存/审计后置动作走 db.info['post_commit_callbacks']（core/exceptions.py:183-187、:216-217）——好设计，但仅 db_transaction 路径享受。
- commit/rollback 出现在 db_transaction 块内 = 0 处 → 无嵌套/双提交脏问题。
- 契约违反：services/auth_service.py:63,72（登录时间戳/失败计数）、services/numbering_sequence.py:64,111（号段分配）属有意立即持久化；备份域 15 处、tasks 9 处、core/database.py 2 处属各自生命周期，可接受。
- 封装破坏：core/nav_context.py:137 起共 3 个文件直接 import 私有 _AsyncSessionLocal。
- 影响：最大风险是"HTTP 200 + 未提交"的静默数据丢失；其次是只读副本降级无指标（读放大回主库不可观测）。
- 建议：a) commit 前置于响应（依赖层/中间件内 ensure_commit），失败即报错——M（面广需回归）；b) commit 失败加 metric+告警，S；c) 只读降级加指标/采样，S；d) nav_context 改用 get_async_db_context，S。

⑥ 后台任务 / 线程 / 进程安全性
- 真实调用点（去重）：asyncio.to_thread 40 ＋ loop.run_in_executor 6（batch_import_parser.py:59,76、report_service.py:212、services/backup/restore.py:87、ocr/_import.py:67,75）＋ run_in_threadpool 5（services/auth_service.py:48,52,55,61,70）＝ 51 处卸载（即任务描述"约 48 处 loop-execute"）。asyncio.run 全仓 8 处**全在 fastapi_app/tests/**，生产 0 处。create_task 13 处；subprocess 生产 6 处；threading.Thread 生产 15 处。
- 明确禁用 asyncio 子进程：services/backup/_proc.py:1-8 docstring 说明 Windows SelectorEventLoop 不支持 asyncio.create_subprocess_exec，统一改为线程池包装同步 subprocess（_proc.py:15 run_proc 内 _run() 调 subprocess.run 后 await asyncio.to_thread）；全仓 0 处 create_subprocess_exec。
- 唯一真阻塞（必修）：services/backup/orchestration/recovery_test_service.py:517 async def _psql_import，:544 直接 subprocess.run(psql_args, input=dump_sql, capture_output=True, env=env, timeout=600)，调用点 :468 在 async 恢复演练主流程 → 最长阻塞事件循环 600 秒；同仓已有正确替换（_proc.py:15 run_proc、dump.py:141 to_thread）。
- dump.py 澄清：:91 _stream_dump_to_gzip 内 :97 Popen，由 :141 await asyncio.to_thread(...) 执行（不阻塞）；:350 _psql_import 内 :353 Popen，由 :398 threading.Thread 专职执行。
- create_task 引用管理：11/13 正确——main.py:189/193/197 存 background_tasks 且 :212-214 shutdown cancel+gather；backup/restore.py:478/541 存 _background_tasks + add_done_callback；:594 watchdog 持变量；core/cache.py:478、core/purchase_cache.py:92、core/db_health.py:43、services/notification_service.py:211 有全局/self 引用；services/ocr/_import.py:85 有 finally cancel+await。未持引用 2 处：services/fifo_allocation.py:106（内部 _invalidate_fifo_caches_safe 已 try 包裹，可接受）、services/backup/records.py:253（写记录失败时 loop.create_task(send_alert)，异常可能丢）。
- server_manager（13 文件 Tk 运维台）线程模式正确：worker 只投 queue.Queue，主线程 root.after(app.py:524 _poll_queue) 消费（log_ops.py:207、log_view.py:243/373、redis_ops.py:178、dev_mode.py:114/141、app.py:370/708/1144、action_gate.py:76、windows_ops.py:296）；log_ops.py:4 docstring 明确"不得 import tkinter"，app.py:775 同款契约注释。
- ARQ（core/arq_app.py）：docstring :1-9 说明以 ARQ 替代 Celery（避免同步任务与 async 循环割裂、cron 内置免 beat）；队列 :26-29 QUEUE_BATCH/REPORTS/BACKUP/PLAN；:33-46 _build_redis_settings（REDIS_BROKER_URL 优先，broker 与缓存隔离）；WorkerSettings :199-201 max_jobs=10、job_timeout=1800、max_tries=3；cron :136 max_tries=3。
- 建议：a) recovery_test_service.py:544 改用 _proc.run_proc，S；b) records.py:253 与 fifo_allocation.py:106 改显式任务集合 + done_callback，S；c) 提供全局 ensure_task() 辅助，S。

⑦ 明显重复代码块（top 清单）
- 精确重复（归一化 AST 哈希）：12 组、冗余约 356 行。生产真重复：services/batch_import_service.py:59 process_order_import ↔ :83 process_stockin_import（各 22L）；顶层 utils/batch_upload_utils.py:36 validate_customer_name ↔ fastapi_app/utils/__init__.py:125 validate_customer_name（26L vs 15L，同名两份实现）。另有 3 组来自冻结副本 backups/material-calculator-rollback-20260911/fastapi_app/services/purchase_product_service.py 与现役 fastapi_app/services/purchase_product_service.py 逐字同源（get_products 108L :64 vs :67、get_products_batch_bom 29L、get_search_suggestions 25L）。其余 7 组在 tests/。
- 近似重复（token 5-gram Jaccard≥0.55）top9：
 1) 0.794 api/v1/endpoints/tasks.py:148 async_import_orders ↔ :173 async_import_stockins
 2) 0.692 services/dashboard/customer.py:30 fetch_customer_out_details ↔ :80 fetch_customer_order_details
 3) 0.640 services/report_service.py:222 get_stockin_logs ↔ :281 get_stockout_logs
 4) 0.625 services/case/queries.py:61 get_case_stockins ↔ :106 get_case_stockout_list
 5) 0.609 server_manager/widgets.py:188 _animate_hover ↔ :201 step
 6) 0.583 api/v1/endpoints/backup/actions.py:90 trigger_full_backup ↔ :150 trigger_incremental_backup
 7) 0.565 services/report_service.py:281 get_stockout_logs ↔ :345 get_deduction_logs
 8) 0.563 services/purchase_history_service.py:19 get_modification_logs ↔ :83 get_status_logs
 9) 0.557 services/report_service.py:100 get_order_logs ↔ :222 get_stockin_logs
- 主题：in/out 对称"日志类查询"模板（report_service 3 对、dashboard/customer、case/queries、purchase_history_service 皆为分页+时间窗+客户过滤+聚合同构）、tasks.py 一对导入端点、backup 一对触发端点。
- 建议：a) 新建 services/reporting 公共查询构造器，M；b) 导入/触发端点参数化为单函数（direction/scope 参数），S；c) 删除冻结副本，S；d) utils 与 fastapi_app/utils 合并，S。

## 三、问题清单（优先级 / 文件:行 / 影响 / 修复 / 成本）
P0-1 core/exceptions.py:203-214：db_transaction 把 AppError/NotFoundError 降级为 HTTPException → 全局 app_error_handler(main.py:302) 永不触发、业务错误码全丢。修：直接 re-raise AppError（仅 error_map 命中转 HTTP）。成本 S。
P0-2 core/database.py:229-231：响应后才 commit 且失败仅 logger.error → HTTP 200 但数据未落库的静默丢失。修：commit 前置于响应 + 失败即报错 + 指标。成本 M。
P1-3 main.py:332-341：http_exception_handler 无 code → 错误信封字段不一致。修：补 code=HTTP_{status}（需前端契约同步）。成本 S。
P1-4 core/exceptions.py:74/126/147：三个死 helper 且信封与生效信封互斥 → 双契约、误导新代码。修：删除或让 main.py 复用。成本 S。
P1-5 services/backup/orchestration/recovery_test_service.py:544（调用点 :468）：async 内 subprocess.run(timeout=600) 阻塞事件循环最长 10 分钟。修：改用 services/backup/_proc.py:15 run_proc。成本 S。
P1-6 core/database.py:352：只读副本 2s 超时静默降级主库、无指标 → 读放大不可见。修：计数+采样日志+告警阈值。成本 S。
P2-7 六个真实模块环（outsource/order 6、stock 4、product 3、core.audit_middleware↔core.deps 2、tasks.backup_tasks↔core.arq_app 2、batch_import↔batch 2）→ 循环依赖、import 顺序脆弱、单测难隔离。修：逐环依赖倒置/抽公共模块（order/outsource L，其余 M/S）。
P2-8 shared_models(45)/services.backup(18)/server_manager(6) 三个包聚合环 → 改任一子模块牵动包根。修：__init__ 去聚合 + 子模块绝对导入。成本 M（机械）。
P2-9 core/arq_app.py:49-76（及 core/event_bus.py、core/health.py）：core 反向 import services/tasks → 分层声明与现实不符。修：任务注册改名字表/入口注入、event_bus 用协议解耦、health 探针下沉。成本 M。
P2-10 services→schemas 8 条（dashboard_py 域 6 + batch_import 2）→ 服务层依赖 API DTO，DTO 改动传导进服务层。修：DTO 归属下沉或端点侧组装。成本 S。
P3-11 备份域 HTTPException 密集（restore.py 41、export.py 14）+ 42 异常类仅 6 个继承 AppError → 错误翻译散落端点。修：BackupError 家族加 AppError 适配基类。成本 M。
P3-12 47 个路由缺 response_model → OpenAPI 契约不完整。修：下载类显式 response_class=FileResponse/StreamingResponse，health/notification 补模型。成本 S~M。
P3-13 6 个 body>80 行路由（backup/validation.py:377/584/750、auth.py:373、backup/export.py:523、backup/restore.py:281）+ 服务层巨函数 320/302/293 行（services/backup/orchestration/core.py:149、dashboard/mobile.py:54、backup/dump.py:158）违反门禁阈值。修：抽 helper/分段。成本 M~L。
P3-14 Depends 样板重复（router.py get_current_user_id×31、order_routes require_any_permission×19、case_endpoint require_permission×18、outsource get_async_db×16、material_registration×15、customer_sampling×13+13、purchase_plan×13+12）+ get_db/get_read_db 别名命名不统一（9/7 文件）。修：命名统一 + 权限域聚合 + 去重认证声明。成本 S~M。
P4-15 core/nav_context.py:137 等 3 文件直接 import 私有 _AsyncSessionLocal → 绕过会话生命周期封装。修：改用 get_async_db_context。成本 S。
P4-16 services/backup/records.py:253、services/fifo_allocation.py:106 create_task 未持引用 → 异常/任务可能丢。修：任务集合 + done_callback。成本 S。
P4-17 utils/batch_upload_utils.py:36 与 fastapi_app/utils/__init__.py:125 同名 validate_customer_name（26L vs 15L）；services/batch_import_service.py:59/:83 近同实现。修：合并去重。成本 S。
P4-18 仓库内 backups/material-calculator-rollback-20260911/ 冻结副本（与 3 个现役函数逐字同源）→ 污染门禁/统计/搜索。修：移出代码树或门禁与搜索排除。成本 S。
P5-19 端点 docstring 过半（purchase_plan 310/620、order_routes 281/669、case_endpoint 253/495）。修：文档瘦身。成本 S。
P5-20 services/ 78/184 文件平铺根目录（域化一半）。修：按域继续下沉。成本 L（机械但面广）。

## 四、可复现命令（只读；脚本位于 %TEMP%\erp_audit_v2\）
PY="C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
& $PY %TEMP%\erp_audit_v2\graph2.py     # 模块级依赖图 → graph2.json（1209 模块/2674 边）
& $PY %TEMP%\erp_audit_v2\scc2.py       # Tarjan SCC + 每环最短样例路径
& $PY %TEMP%\erp_audit_v2\lay.py        # 层→层边矩阵、每层入/出度、反向依赖清单
& $PY %TEMP%\erp_audit_v2\eps.py        # 端点体积/路由数；comp.py 行构成
& $PY %TEMP%\erp_audit_v2\thin2.py      # 373 路由薄厚分类
& $PY %TEMP%\erp_audit_v2\leak.py       # 端点直接写 ORM/SQL 清单
& $PY %TEMP%\erp_audit_v2\dep_census.py # Depends × 读/写库依赖交叉表
& $PY %TEMP%\erp_audit_v2\cnt.py        # to_thread/executor/threadpool/create_task/subprocess 去重计数
& $PY %TEMP%\erp_audit_v2\conc.py       # 未卸载阻塞调用（标注 async 上下文）
& $PY %TEMP%\erp_audit_v2\dup1.py       # 精确重复函数组（归一化 AST 哈希）
& $PY %TEMP%\erp_audit_v2\dup2.py       # 近似重复对（5-gram Jaccard）
& $PY %TEMP%\erp_audit_v2\excs.py       # 自定义异常类与继承关系
& $PY %TEMP%\erp_audit_v2\s1.py         # 文件规模 top
& $PY %TEMP%\erp_audit_v2\ar2.py        # create_task 调用点 + asyncio.run 归属

【一句话结论】分层方向清晰、端点不脏，但"结构最优"不成立：需补仓储层语义、给 core 减肥并切断 core→services/tasks 反向依赖、把错误与事务契约收敛为一套（当前 2 套错误信封、3 条 commit 通路）、消掉 6 个真实模块环与 3 个包聚合环；端点侧只需权限依赖聚合与文档瘦身，属低风险高收益。

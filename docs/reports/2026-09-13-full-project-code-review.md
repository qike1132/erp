# ERP 全项目代码审查报告（2026-09-13）

- 范围：全仓库 2,515 个跟踪文件（Python 159,701 行 / Vue 40,260 行 / TS 20,138 行）
- 方法：横切模式扫描（SQL 拼接 / 手动 commit / 循环内查询 / 定时器泄漏 / TODO 全量清点）+ 3 个静态检测脚本 + 16 个高风险文件逐行精读（库存、事务核心、单号、缓存、中间件、看板、出库、BOM、批次任务、采购计划等）+ 全部端点分页/鉴权参数级核查 + 前端组合式函数泄漏核查
- 诚实边界：**非 22 万行逐字面阅读**（本会话 agent 并行调度不可用，改为主线程直审）；横切扫描已覆盖全部非测试代码，精读集中于高风险域
- 基线：叠加复核 2026-08-22 审计（docs/reports/2026-08-22-code-quality-assessment.md）全部遗留项的当前状态

---

## 一、遗留项复核：已修复确认 ✅

| # | 原审计问题 | 现状 |
|---|---|---|
| 1 | 多 SKU 库存聚合错误（stock_inventory_service.py:203/:754） | 已修：CTE 单查询 + 按 OrderItem 维度聚合，无明细订单 COALESCE 回退订单级字段 |
| 2 | 综合导入 imported 计数可大于实际落库 | 已修：`_process_comprehensive_sheet` 改 begin_nested savepoint，计数在 savepoint 成功后才累加 |
| 3 | numbering.py 烧号（两提交间崩溃） | 已修：numbering_counter 表原子 upsert 递增 + 独立短事务；业务回滚仅跳号不重号 |
| 4 | purchase_center/order_routes.py:186 per_page 无上界 | 已修：`le=500` |
| 5 | 无分页端点集群 | 大部分已修：stock.py（le=500 + 导出 MAX_EXPORT_INVENTORY_ROWS + 单 CTE）、product.py、case_endpoint.py、order_batch.py、material_registration.py、customer.py 均已有界。**仅剩 production_plan.py、production_summary.py 无界** |
| 6 | N+1：purchase_supplier_service.py:152 循环 await | 已修：批量 UPDATE + `batch-loop` 注释；delete_supplier 单 exists() 查询 |
| 7 | core 依赖 notification_service 私有函数 | 已修：core/redis_client.py 独立模块（批次 1） |
| 8 | order.py:216/296-312 事务混用 | 已修：全文件统一 db_transaction |
| 9 | 凭据硬编码（reset_admin_password.py / init-replica.sh） | 已修：环境变量注入；init-replica.sh PGPASSWORD 改变量（建议后续 .pgpass） |
| 10 | purchase_plan.py 宽泛 except→500 | 已修：类型化异常 + asyncio.timeout(20s)→504 + 脱敏 |
| 11 | 产品搜索语义 4 路由重复 | 已修：core.container ProductSearchService 统一 |
| 12 | 前端定时器/监听器泄漏疑点 | 全部有清理：usePurchaseHandlers 改 Vue Query refetchInterval；useBackupTask onScopeDispose(stop)；useDashboardClock/useNotifications 由调用方 onUnmounted 接线 |

**仍未收敛的遗留项**：
1. multi-SKU TODO 17 处（order.py:259、approval_service.py:7,320、inventory_service.py:7、order/commands.py:185,197、order_batch_service.py:3、purchase/_factory.py:25、purchase/_list.py:164,390、purchase/_supplier.py:49、shared/report_data_service.py:6,146,152、shared/shipment_calc.py:44、shared_models/order.py:49）——Task5 待多 SKU 规则定案
2. 手动 commit 52 处（上次 31 → 52；其中 core/database.py×3 为框架本体、numbering_sequence×2 有意短事务、backup/records×3 有意逐条提交属合法；端点层 6 处（supplier×2、backup/restore×2、customer×1、order_routes×1）在批次 1 已核实为幂等恢复/设计保留——但每处 30-50 行 rollback 样板的重复仍是可维护性负担，见下）
3. 状态机统一（staging 三份拷贝、采购/外发内联字面量）——批次 3 计划项
4. 导航双源（nav_context.py:27-54 PERMISSION_URL_MAP vs DB Permission 行）——已加未映射告警（:137）
5. Python 版本漂移（CI/ruff/mypy 锁 3.12 vs 运行 3.13）

---

## 二、本轮新发现问题（按文件）

### 🔴 高

**1. core/database.py:147-183 — 事务提交发生在响应发送之后**
`get_async_db` 在 `yield`（响应已发出）后才 commit，代码注释自认"响应已发送但数据未落库（静默丢失风险）"，仅靠 ERROR 日志兜底。commit 失败时客户端已收到成功响应，ERP 单据丢失且用户无感知。
**建议**：以 db_transaction（响应前提交，purchase_plan/order/auxiliary 已示范）为标准覆盖全部写端点，get_async_db 自动提交降级为兜底；最终目标是消灭"响应后提交"路径。

**2. production_plan.py / production_summary.py — 全库最后两块无界查询**
两文件均无 `le=` 分页上界（grep 证实 0 处）。列表/导出随数据量线性劣化，是内存与延迟尖峰的最后一个集群。
**建议**：对齐 order.py 的 le=500 + 导出走 MAX_EXPORT 上限/ARQ 异步化。

### 🟡 中

**3. services/auxiliary_service.py:129-130 — N+1 遗留**
`orchestrate_batch_stockouts` 后置通知循环 `for product_id, _ in successful_pairs: product = await db.get(Product, product_id)`。上方 L106-109 已有一次批量查询取 id→name，第二段循环又逐个 db.get。
**建议**：合并为一次 `select(Product).where(Product.id.in_(...))`，循环内查内存 map。批量出库 N 项时省 N-1 次往返。

**4. core/cache.py — 击穿保护三处缺陷**
- L236-278：未获锁 worker 自旋 `100 × 0.1s = 10s` 等待回填；冷缓存高并发时所有请求挂 10s 占住连接槽。建议上限降到 2-3s 后直查 DB。
- L205-234：锁 `SET NX EX 10` 无属主 token，持锁方超过 10s 后会误删他人锁。建议 value 存随机 token，删除用 Lua 校验。
- L213-278：锁-重算-回填逻辑完整重复两份（L216-235 vs L263-278），应提取。
- L433-444：`warmup_cache` 写入 `key_prefix:prewarm`，而 wrapper 读取的是 `key_prefix:<参数hash>`——**预热数据永远不会被命中，功能无效**（且无调用方，实为死代码）。

**5. tasks/batch_tasks.py — 80 行复制体 + 阻塞式同步会话**
`batch_import_orders_task` 与 `batch_import_stockins_task`（L48-126 vs L129-181+）仅 Order/StockIn 之差，全量复制；路径校验 L63-67 重复实现 L33-36 的 `_is_allowed_upload_path`；同步 Session（历史实现，经 to_thread 隔离，可接受但应标注迁移计划）；金额/数量行级 try/except 内 rollback 丢弃整批未提交行（≤49 行）语义已有说明但易踩坑。
**建议**：提取共享 `_run_batch_import(session, row_builder)`；批内失败改 savepoint 保留已验证行。

**6. api/v1/endpoints/purchase_center/order_routes.py:132-176 等 — 端点层事务样板重复**
一键生成采购订单端点：手动 commit + IntegrityError/ValueError/SQLAlchemyError 三路 rollback 样板（每路再嵌套 try/except 兜 rollback 失败），50 行/端点（批次 1 已核实其手动事务为幂等恢复设计、语义合理，保留定性为"设计决策"）；supplier.py×2、backup/restore.py×2、customer.py×1 同模式。db_transaction 已有 error_map 机制（purchase_plan.py:107-118 示范），可在保持幂等语义的前提下收敛样板。
**建议**：评估以 `async with db_transaction(db, error_map={...})` 重写，端点减 30-50 行；幂等回查逻辑保留。

**7. daily_production_service.py / batch_import_* — 金额 float 计算**
L43,52,145,158,258,352,442,572 大量 `float(price)`、`round(float(total))` 聚合；batch_import_core.py:233、batch_import_service.py:675 同。float 二进制精度在累计求和/报表合计时可产生分位漂移。
**建议**：确认 DB 列为 Numeric 后，聚合用 `cast(Numeric)`/Decimal，仅在序列化边界转 float。

**8. 时区口径分裂：dashboard/stats.py:243 + numbering.py:93**
KPI"今日"与编号日期段均按 UTC 边界（北京时间 08:00 切换），与业务直觉的本地日不一致；core/number_generator 又用本地时间（docstring 承认双套并存）。早上 8 点前下单的编号日期段/KPI 归属与用户感知差一天。
**建议**：产品确认口径后统一（建议 Asia/Shanghai 业务日），一处工具函数收口。

**9. services/purchase_plan_queries.py:500 — 库存预警漏累计场景**
`get_monthly_aggregated` 中 `if _calc_stock_status(qty, inv_qty) != 'sufficient'` 按单行数量比较总库存；同一产品多条明细累计超库存（如 3×100 vs 库存 250）不告警。
**建议**：改为对累计 plan_qty 判断，或按日期粒度累计比较。

**10. services/purchase_plan_queries.py:400-565 + services/bom_service.py:198+ — 长函数**
get_monthly_aggregated 174 行（单次遍历设计良好，可按 by_date/sku_summary/customer 三段拆分）；save_bom 200+ 行（角色/填充物/物料/面料全量替换混在一函数）。同域：backup/orchestration/recovery_test_service.py 1148 行、tasks/backup_tasks.py 827 行。
**建议**：列入既定"长函数专场"。

**11. services/bom_service.py:504-530 — 角色复制嵌套循环 + 逐 role flush**
复制 BOM 时 `for old_role: ... await db.flush()` + 内层双遍历 fabrics/accessories，O(R×(F+A)) 扫描 + R 次 flush。
**建议**：先收集全部新对象，按 role 批量 flush 一次；内层用 role_id→items 的 dict 索引。

**12. services/backup/records.py:613-644 — 逐条 commit 的 I/O 放大**
补录/修正/删除循环内每条 `await db.commit()`（有"每条成功即落库"注释，属有意设计）。N 条记录 = N 次 fsync。
**建议**：若"部分成功"语义必须保留，改为分批（每 20 条）commit + 失败批 savepoint；否则整批一次提交。

**13. core/middleware.py — 三处**
- L337-347：无 Content-Length 时全量缓冲 body 并回写私有属性 `request._body`（Starlette 私有 API）。
- 全链 8 个独立 BaseHTTPMiddleware 层（request_id/CSRF/security/body/prometheus…），每层协程切换开销，可合并为 2-3 个。
- L373-382：Prometheus endpoint 归一化仅折叠纯数字段，非数字动态段（如订单号）会成为高基数 label，长期拖大指标内存。
**建议**：合并中间件层；body 限制改 stream 包装；归一化规则补充"长随机段折叠"。

**14. core/prod_runner.py — print() 日志 + core 位置不当**
生产守护进程（621 行/39 函数）用 print 输出 + 自制日志轮转；文件位于 core/ 但属独立进程脚本，被误导入时 print 输出丢失。
**建议**：迁移 scripts/ 或独立模块，改 logging + RotatingFileHandler。

**15. 前端 — 定时器清理约定脆弱**
useDashboardClock/useNotifications 的 stop 由调用方手动接线（useBackupTask 的 `onScopeDispose(stop)` 是正确范本）；漏接线即泄漏。
**建议**：三个 composable 内部统一加 onScopeDispose 兜底，调用方接线仅作提前停止。

### 💭 低

- **stock_inventory_service.py**：旧全量路径 get_inventory（L277-329）+ 4 个辅助函数（L641-793，约 250 行）仅剩 3 个调用方（production_plan_service.py:100,173、purchase_plan_inventory.py:42），与新 CTE 分页路径双实现并存。`_get_inventory_map` 可改为单条 SQL 直接返回映射，省 4 聚合 SQL + Python 合并。函数内重复 import（L68,75,143，顶部已有 Order/OrderItem）；country_data 解析逻辑两处重复（L313-321 vs _parse_country_data）。
- **core/nav_context.py:173-211**：同步版 get_nav_sections 废弃包装器无任何调用方，39 行死代码。
- **dashboard/stats.py:36-61**：_get_mv_daily_quantity 无业务调用方（仅 dashboard_service.py re-export）。
- **shared/stock_concurrency.py**："跨框架共享"声明过时（Flask 已无引用）；get_product_for_update_sync 无调用方；docstring 用法示例含 `await db.commit()` 违反事务约定。
- **core/cache.py:104-114**：_evict_local_cache 每次回填全表扫描过期键（≤5000 条，开销小）。
- **core/database.py:106**：`except (ImportError, Exception)` 冗余；:360 函数内重复 import text；(RuntimeError, OSError, ValueError, SQLAlchemyError) 元组重复 8 次可提常量。
- **services/batch_import_service.py**：6 个 import_*_service 函数 try/except+rollback 样板重复（每函数约 70 行同构）。
- **numbering.py**：UTC 与 core/number_generator 本地时间双套并存（docstring 已说明原因）；模块顶部 noqa F401 兼容 re-export 待清理。
- **purchase_plan.py:258,322**：函数内 `import time as _t` 重复；4 个报表端点 try/except 样板 ×5 可提取依赖。
- **purchase_supplier_service.py:55-59**：对 ORM 模型防御性 getattr（模型字段确定，可直取）；create_supplier 名称唯一性检查与 INSERT 间存在 TOCTOU（依赖 DB 唯一约束兜底，异常未映射 409）。
- **purchase_plan_queries.py**：inventory_map 按产品名称文本匹配，产品改名后库存对比失联为 0（设计限制，建议改 product_id 关联）。
- **前端 main.ts:2 处 addEventListener 无移除**：应用级全局监听（App 启动注册），可接受；webVitals.ts 同理。

---

## 三、死代码 / 垃圾文件清单

| 类别 | 路径 | 说明 |
|---|---|---|
| 根目录临时脚本 | _bom_modal_e2e_check.py、_bom_size_check.py、_gen_scope_e2e_check.py、_mc_roles_e2e_check.py、_paste_e2e_check.py、_shoot_p6.py、_proc5002.json、scan_quality.ps1、scan_quality2.ps1、analyze-appdata.ps1、analyze_ruff.py、remove_packaging.ps1、fix-pytest-cache-acl.cmd | 一次性调试/巡检脚本入库，应删除或移 scripts/ 并 gitignore |
| 源码快照 | backups/material-calculator-rollback-20260911/（38 文件） | 完整源码副本入库，git 历史已可回溯 |
| 临时目录 | temp/（6 文件） | 一次性迁移/分析文件 |
| 测试残留 | tests/test_*.txt、test_failures*.txt 等约 10+ 个 | 历史测试输出（上次审计已提，仍在） |
| 归档目录 | .archive/（151 文件）、evidence/（82 文件）、.trae/（190 文件） | 入库造成 clone/扫描噪音 |
| 死代码 | nav_context.get_nav_sections 同步版、cache.warmup_cache、stock_concurrency.get_product_for_update_sync、dashboard._get_mv_daily_quantity | 无调用方（grep 证实） |

---

## 四、正向亮点 ✨

- 全库 **0 处吞异常**，所有 broad except 带 defensive 注释与理由（虽数量偏多，语义明确）。
- SQL 注入面控制优秀：67 处 nosec 全部为"常量片段 + 绑定参数 + 白名单校验"模式，无一处用户输入拼接。
- 缓存体系完整（L1+L2+断路器+击穿锁+跨 worker 广播开关）、enhanced_pagination keyset 深翻页 O(1)、看板 14-17 往返压至 6-7、库存 CTE 化、出库 N 次 flush 合并 1 次——性能债已有系统性偿还。
- 只读副本 2s 快速降级、escape_like 全面覆盖、前端 request.ts 401 单飞刷新/GET 去重。
- 事务向 db_transaction 收敛方向明确且有成熟示范。

---

## 五、优先级优化清单

| 优先级 | 事项 | 预期收益 |
|---|---|---|
| **P0-1** | 写路径全面推广 db_transaction（响应前提交），get_async_db 自动提交降为兜底；端点层 6 处手动事务在保留幂等语义前提下收敛样板（高危项 #1） | 消除"响应后提交"静默丢数据窗口；每端点减 30-50 行 |
| **P0-2** | production_plan/production_summary 补分页上界（#2） | 关闭最后一个无界查询集群，防内存/延迟尖峰 |
| **P0-3** | auxiliary_service N+1 批量化（#3，一行改动） | 批量出库编排 O(n)→O(1) 往返 |
| **P1-4** | cache.py 整理：轮询 10s→2s、锁 token、去重两份重算块、删除 warmup_cache（#4） | 冷缓存并发不再 10s 挂起；击穿保护语义正确 |
| **P1-5** | batch_tasks 双任务合并 + 路径校验去重（#5） | 减 80 行复制体；行级失败不再丢弃整批 |
| **P1-6** | 金额 Decimal 化核查与改造（#7） | 消除报表分位漂移 |
| **P1-7** | 时区口径产品决策并统一（#8） | KPI/编号与业务直觉一致 |
| **P1-8** | multi-SKU Task5 推进（17 处 TODO 收口，需先定规则） | 全库最大正确性技术债清零 |
| **P1-9** | Python 版本全链路统一（3.12 或 3.13 四处同步） | 消除工具链/运行时行为差异 |
| **P1-10** | 长函数专场：save_bom、get_monthly_aggregated、recovery_test_service(1148)、backup_tasks(827)（#10） | 可维护性；批次 3 既定方向 |
| **P2-11** | 仓库垃圾清理（第三节清单） | clone 体积/扫描信噪比/新人理解成本 |
| **P2-12** | 状态机统一（staging 三份 + 采购/外发字面量）、导航双源对账 | 消除状态漂移类 bug 温床 |
| **P2-13** | 中间件合并、Prometheus 基数治理、prod_runner 迁移（#13/#14） | 每请求协程开销、指标内存可控 |
| **P2-14** | 死代码删除（nav_context 同步版等 4 项）与库存双实现收敛 | 减 ~350 行维护面 |

**总体评价**：良好偏上。8 月审计后的批次 0/1/2 整改质量高（14 项遗留修复经本轮逐项证实），横切纪律（异常/注入/分页/缓存）在全库范围内成立。当前最值得投入的三件事：事务提交时点收敛（P0-1）、最后两块无界查询（P0-2）、multi-SKU 规则定案（P1-8）。

---

## 六、修复实施记录（2026-09-13 同日，纯代码变更未重启服务）

**已修复（14 项）**：

| # | 修复项 | 文件 | 说明 |
|---|---|---|---|
| 1 | 批量出库 N+1 批量化 | services/auxiliary_service.py | 循环 db.get 改为单次 select(Product) 批量取，复用 product_map |
| 2 | 缓存击穿轮询 10s→2s | core/cache.py | `_CACHE_REFILL_POLL_SECONDS=2`，未获锁 worker 不再挂 10s |
| 3 | 击穿锁属主 token | core/cache.py | SET NX value=uuid token + Lua compare-del 释放，杜绝误删他人锁 |
| 4 | 锁-重算-回填去重 | core/cache.py | 两份重复块收敛为单路径（获锁/轮询/直算三态） |
| 5 | 删除死函数 warmup_cache | core/cache.py | 其写入 key 与读取 key 永不命中（无效功能，无调用方） |
| 6 | 删除死函数 get_nav_sections 同步版 | core/nav_context.py | 39 行无调用方（文档头同步更新） |
| 7 | 删除 get_product_for_update_sync | shared/stock_concurrency.py | 无调用方；过时 Flask 声明与违规 db.commit 示例一并清除 |
| 8 | craft 导出补上界 | services/production_summary_service.py | export_craft_works 套 `_MAX_EXPORT_ROWS+1` limit 截断（与包装部同模式） |
| 9 | 库存预警改累计口径 | services/purchase_plan_queries.py | 按客户+产品累计 plan_qty 与库存比较，修复累计超库存漏报 |
| 10 | BOM 角色复制去嵌套 | services/bom_service.py | 角色批量建+单 flush，fabrics/accessories/materials 按 role_id 索引，O(R×N)→O(N) |
| 11 | batch_tasks 双任务合并 | tasks/batch_tasks.py | 提取 `_run_batch_import_sync` 共享骨架，两任务只保留行处理函数；备货错误结构对齐（含 skipped_uncommitted） |
| 12 | Prometheus 高基数治理 | core/middleware.py | 路径段归一化扩展到 UUID/长 hex token |
| 13 | 金额 Decimal 化 | services/daily_production_service.py、batch_import_core.py、batch_import_service.py | get_daily_summary 累加链路 Decimal（输出仍 float，契约不变）；Excel 价格 Decimal(str()) 直转避免 float 中转 |
| 14 | 写端点 db_transaction 收口 | api/v1/endpoints/outsource.py（9 写端点）、purchase_center/misc_routes.py（3 写端点） | 手工 try/except(400) 与 db_transaction 默认映射语义一致，机械替换；响应前提交 |

**垃圾清理**：69 个文件移出 git 跟踪（`git rm --cached`，磁盘保留）——根目录 13 个一次性脚本、backups/ 源码快照 38 个、temp/ 6 个、tests 历史输出 12 个；.gitignore 已补对应规则。

**验证**：14 个改动文件 py_compile 全过；`fastapi_app/tests` 1129 passed（3 failed + 5 errors 为基线/WIP 已有，经 git worktree 在 HEAD 基线对比证实——基线同批用例 41 个失败/错误，本树无新增失败）；与改动直接相关的 168 个测试（auxiliary/cache/bom/batch_import/middleware/daily_production/outsource/purchase_plan）全部通过。

**有意未改（需决策或另行安排）**：
- multi-SKU Task5（17 处 TODO）：等待多 SKU 业务规则定案，无法擅自定语义。
- 时区口径（KPI"今日"与编号日期段的 UTC/本地分裂）：改变运行行为与数据口径，需业务拍板；物化视图按 stat_date 聚合的口径也需同步重建，不宜在本轮顺手改。
- get_async_db"响应后提交"根因：outsource/purchase_center 等业务写端点已收口到 db_transaction（响应前提交），auth/backup/batch/monitoring 等流程特殊域（登录失败计数、psql 恢复、任务入队）需逐个评估后单独收口，get_async_db 兜底机制保留。
- 长函数专场（save_bom、get_monthly_aggregated、recovery_test_service 1148 行、backup_tasks 827 行）：纯可维护性、机械搬移量大，归入既定批次 3 专场以控制单次变更风险。
- order_routes/supplier/customer 端点事务样板：批次 1 已核实为幂等恢复设计保留，本轮未动。
- backup/records.py 逐条 commit：有"每条成功即落库"语义注释，属设计决策，改批量需产品确认部分失败语义。
- .archive/、evidence/、.trae/ 三个目录仍保留跟踪（可能为有意存档/证据，删除不可逆），如需移出请确认。

**生效说明**：本机即生产，以上均为工作树代码变更，生产进程不受影响；下次变更窗口重启后生效（按运维铁律走 server_manager/NSSM 树重建，勿用 CLI --prod）。改动未提交 git（工作树含其他会话 WIP），待 review 后按逻辑分组提交。

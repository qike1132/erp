# 全项目代码质量审计报告（2026-11-21）

> 任务来源：RISEN 终稿提示词（全量重审、报告+全部修复、静态+轻量基准、三技能流水线）。
> 基线：main @ c44478e2（PR #27/#28 合并后），工作区干净（仅未跟踪的文档/效果图残留，不入库）。
> 口径：严重度按 [docs/agents/code-review-standard.md](agents/code-review-standard.md) §2；「机器门禁已拦的形态不重报」原则贯穿全文。

## 0. 结论速览

| 级别 | 数量 | 说明 |
|---|---|---|
| [H] | 2 | 真实用户路径产生错误结果/数据错 |
| [M] | 42 | 显著提高故障概率或维护成本（含 2 条由 H 降级，见 §10） |
| [L] | 31 | 可读性/重复/口径漂移，不影响行为 |
| [N] | 26 | 可不改 |
| 假测试 | 2 确证 + 4 可疑 | 阶段 3 变异检查定谳 |
| 性能可疑点 | 12 | 阶段 2 只读基准实测 |
| 重复实现对 | 15 | 对账单见 §9 |

**审计过程质量自证**：子代理共产出 5 条 [H]，亲验撤销 1 条误报（saveBom 并发——实际代码有 `copyInFlight()` 守卫，见 §10）；其余 12 项抽样亲验全部坐实。机器对齐五项检查全绿。

## 1. 方法与证据等级

- 14 个只读子代理分区审计（后端 services×6 / endpoints×2 / core+utils+server_manager×1；前端 views×2 / 共享层×1 / mobile×1；跨区性能+造轮子×1；测试真实性×1），每区独立新鲜上下文。
- 亲验标注：✅=本人逐行核实过引用行；◇=代理证据（引用具体、修复阶段复现时再验）。
- 子代理约束：不重报机器门禁形态（ruff/mypy/bandit/裸except/函数长度/静态N+1/service commit/BOM/env漂移/密钥/孤儿模块）；只报语义正确性、契约一致性、失败路径、越权影响面、时区精度、并发幂等。

## 2. 机器对齐检查（Spec 轴机器证据，2026-11-21 当场跑）

`check:api` PASS（113 端点、移动端全走共享层、cache-buster 同步）· `check:api:pc` PASS（343 文件无绕过）· `check:routes` PASS（PC 32/移动 15 路由，未配对项为正常差异）· `check:dto` PASS（567 导出类型无重复声明）· `check:types` PASS（api.d.ts 与 openapi.json 同步）。`check_orphan_modules` PASS（376 候选全部可达，1 项 KNOWN_UNWIRED 豁免）。

## 3. [H] 发现（2 条）

### H-1 出货/皮套导入数量小数静默截断 ✅
- `fastapi_app/services/batch_import_core.py:1110`、`fastapi_app/services/batch_import_service.py:719`（另 ：510/:574 同形）
- 形态：`qty = int(quantity)` 对 Excel 数值单元格 float（10.5）取整落库；订单/备货导入路径（batch_import_parser.py:296-306）是「小数一律拒绝」，同一输入因 Sheet 不同结果不同。出货按错误数量扣库存。
- 修复：四处统一走 `_parse_positive_quantity` 的 is_integer 拒绝口径。

### H-2 混厂订单 items/factories 跨厂泄漏 ✅
- `fastapi_app/services/serializers/order_serializer.py:204-230` + `fastapi_app/services/order/queries.py:78、273、200-210`
- 形态：订单可见性是「任一本厂 SKU 即整单放行」，但 items 全量序列化（product_id/name/barcode/quantity）无厂过滤，`factories` 字段（:222-230）把**他厂工厂名**一并带出；beile 页已收窄（beile.py:595-599）、batch 模块更严（任一他厂 SKU 整单不可见，order_batch_service.py:185-197），三处口径互相矛盾。
- 前提：若业务裁定「订单级可见」是设计意图则降 [M]（仅剩 factories 跨厂名）——**待 owner 裁定**。
- 修复：serialize 加 factory 上下文按厂收窄 items/factories，或书面确认订单级口径写进 docstring 并三处对齐。

## 4. [M] 发现（40 条）

### 后端 services（1-20）
1. ◇ order_batch_create.py:241-244 — `OrderItem.deduct_quantity` 只按订单量收口，实扣在 order_deduction_service.py:116 另按可用量收口 → 备货不足时「落库抵扣量 ≠ 实扣」，且该列被 purchase/_unprocessed.py:96 当「已抵扣」展示。修：process_order_deduction 返回实扣量回写。
2. ◇ order/commands.py:435、279 — 整单/明细改量无「不得低于已抵扣/已出货量」守卫（deduction.py:303 对抵扣量有），可把已出货 50 的订单改成 10，状态恒「已出货」。修：改量前聚合 StockOut 拒绝。
3. ◇ order_batch_service.py:509-511 — `batch_completed_at >= date_from` 裸字符串比 naive-UTC 列，北京 0-8 点完成批次落前一天；AUD-02 已建 `business_day_bounds_utc_naive` 未用。
4. ◇ purchase_order_crud.py:1094-1103 — `cleanup_orphan_pending_purchase_orders` JSON 数组兜底（b 路径）无「id 同存于 order 与 stockin 则不采信」守卫（c 路径 :1105 有）→ 删同号客户订单误删备货来源单。
5. ◇ purchase_plan_service.py:176-180 — 库存事件重算 handler 异常吞成一行 ERROR，不冒泡落 `stage=handler` 死信（与已修撤销链同形状；docstring 自记 2026-09-10 生产事故）。
6. ◇ schemas/purchase_plan.py:30-33 + purchase_plan_crud_ops.py:170-172 — `PurchasePlanUpdate.status` 自由字符串直接 setattr，无白名单无迁移校验（PO 侧已加白名单）。
7. ◇ （H-3 子项）bom_service.py:274-282 — BOM 明细行部分更新静默清空未传字段。
8. ◇ batch_import_parser.py:155（调用点 :188）— `cleanup_temp_file` 的 `time.sleep` 重试（10×0.5s）跑在 async 上传路径事件循环上，最坏单请求阻塞全体 ~5s。修：`asyncio.to_thread`。✅亲验（sleep 在重试循环内）
9. ◇ case/queries.py:275、291 — 皮套导出 20000 行静默截尾，端点无超限拒绝（违反 A-M24 口径：material_registration/_export.py:61-70 超限 413）。
10. ◇ daily_production_service.py:597-599 + schemas/daily_production.py:35 — 传 `quantity:null` 报 500（schema 允许 None，`kwargs.get('quantity', record.quantity)` 返回显式 None，`<= 0` 抛 TypeError 未捕获）。
11. ✅ production_plan_service.py:65-82 — `update_plan` 无行锁/乐观锁并发丢更新；`status` 在可写字段白名单里但无状态机校验，任意字符串使计划从所有筛选消失。
12. ◇ material_registration/_commands.py:191-198 — `delete_registration` 无「已收货」守卫无审计留痕（对照 delete_case_item :316-320 有流水禁删）。
13. ✅ staging/order.py:294（stockin.py:206-211、stockout.py:383-388 同型）— 确认只 purge REJECTED 行，APPROVED 行永久留存，三张 staging 表无界增长。
14. ◇ order/deduction.py:165-171、:232-251 + staging/stockin.py:144-155 — InventoryLog 缺 `quantity_before/quantity_after`（其余写点已补齐），对账断链。
15. ◇ api/v1/endpoints/report.py:66-194 — 五个流水端点不捕 `parse_date_strict` 的 ValueError 且无全局 handler → `?start_date=abc` 返回 500（同文件 export 已修）。
16. ✅ dashboard/customer.py:95-97 — `except (OperationalError,...)` 吞成 `success=True, data=[]`，与 /stats 的 503 口径矛盾；**同族**：dashboard/todos.py:69-71、activities.py:69-71、mobile.py 多处、stats.py:178。
17. ◇ schemas/daily_production.py:18,34 — 金额 `unit_price: float` 直入（库列 Decimal）；service 存在 Decimal 版（:735）与 float 版（:1099）两个同名 `effective_unit_price`。
18. ◇ api/v1/endpoints/auxiliary.py:444-449、494-495 — `BatchOrderRequest.orders/stockins/stockouts` 列表无 max_length，无界 payload 可长时间占用事件循环与 DB【门禁盲区：pydantic 无界列表】。
19. ◇ backup/orchestration/recovery_test_service.py:516 — SQL 演练把整份解压 SQL 读进内存只为算 size，GB 级 dump 演练 worker 内存峰值≈2×解压体积可 OOM。
20. ◇ backup/orchestration/drill_validator.py:342-347、262-267 — 禁用任一验证族后 `all()` 恒 False，每次演练必判失败并发「演练失败」告警。修：禁用族标 `skipped` 排除出 all_passed。

### 后端平台与端点（21-29）
21. ◇ backup/orchestration/core.py:876、838 — 备份产物 `write_bytes` 非原子（域内已有 `atomic_output` 未复用）；半截 .zip 按 records.py:605-617 `_counts_as_restorable`（只看 size>0）可充当「最后一份可还原」。
22. ◇ approval_service.py:384-393 — 审批通过的编辑不派发工厂通知（直改路径 order/commands.py:473-479 有 `dispatch_factory_notifications`）。
23. ✅ user_service.py:69-81 — `bump_token_version` 只失效本进程缓存（TTL 10s），改密/禁用后其他 worker ≤10s 仍放行被吊销会话；权限缓存有跨 worker 广播、会话版本没有。修：复用 USER_PERMISSION_CHANGED 事件链。
24. ◇ ocr/_import.py:105-108 — 客户模糊匹配 ≥0.7 静默改写库内名且不像产品匹配那样留原文（「张三」命中「张三丰」即换名）。
25. ◇ ocr/_text_parsers.py:344-351 — 超长数字串 `float()`→`inf`→`int(inf)` 抛 OverflowError，`_import.py:219` 的 except 不拦 → 整次导入 500；`int(match.group(2))` 可产 10^400 通过 `>0` 校验，flush 时 DataError 同样 500。
26. ◇ report_service.py:210-560 五处 — naive datetime 比 timestamptz，日界依赖 PG 会话时区恰为 Asia/Shanghai（AUD-23 已改 dashboard，report 未对齐）。
27. ◇ api/v1/endpoints/backup/export.py:114 — `GET /export?format=json` 直调 `execute_legacy_backup_to_bytes` 无锁检查，绕过备份/还原互斥 → 还原期间产出部分表缺失的损坏包。
28. ◇ api/v1/endpoints/purchase_center/order_routes.py:87 — `POST /orders` 手工建采购单无幂等键（同文件 :123 一键生成已有 X-Idempotency-Key 机制），双击/重试产生重复 pending 单（唯一索引只盖生成单）。
29. ◇ api/v1/endpoints/backup/validation.py:769-771 — 探测不出加密的 legacy 裸信封 `.enc` 既不进 zip 也不进 json 分支，`valid=True`「验证通过」→ 损坏的 legacy 加密备份被巡检判有效。

### 前端（30-40）
30. ◇ customer-order/composables/useOrderImport.ts:221-224 — 跨类型导入静默清掉另一类型已导入暂存行（`filter(i => i.origin !== 'import')` 未按 type 区分）。
31. ◇ outsource/components/OutsourceShipDialog.vue:262-283 + purchase-plan/composables/useCreateShipmentPlan.ts:234-239 — submit 缺函数级重入闸（H6 标准：按钮 disabled 挡不住连点）。
32. ✅ dashboard/components/DashboardChartsSection.vue:111 — 「订单趋势（近7日）」数据 `[0,0,0,0,0,0, order_today]`，前 6 天硬编码 0，昨日 500 单也显示 0。修：接 useProductionTrend 同款数据源或改标题。
33. ◇ **失败渲染业务空态家族 ×7**（无 isError 分支，5xx 时用户误判「没有数据」）：user/composables/useUserManagement.ts:177、approval/composables/useApproval.ts:58-74、case/composables/useCaseInventory.ts:37、notifications/composables/useNotificationCenter.ts:77-82、mobile MPurchaseView.vue 三页签（:10/:41/:68）、mobile MCustomerOrderView.vue:10。beile-order/BeileOrderTab.vue:10-16 已是正确样例（错误横幅+重试）。
34. ◇ backup/BackupView.vue:459-461 — `onUploadRestore` 未处理 `task_id` 缺失 → busy/uploadRestoring 永久 true，全页备份/还原按钮禁用须刷新（executeRestore :419-423 有兜底）。
35. ◇ dashboard/composables/useBeileConfirmPopup.ts:18-22 — 弹窗预检只按 `factory==='湖北'` 不查 `beile_order_view` → 每次挂载发注定 403 的请求且反复弹「权限不足」。
36. ◇ report/ReportView.vue:239-243 — 列头排序只对已分页的当前页 20 条客户端排序，查询参数不含 sort，跨页无序。
37. ✅ api/request.ts:133 — 401 刷新被限流/瞬态失败时的 `__authRefreshDeferred` 标记全站只有 useDashboardStats.ts:114 一个消费方，其他列表页当普通失败渲染（会话仍有效）。
38. ✅ api/request.ts:146-153 — 403 全局 toast 无请求级静默豁免，任一后台轮询权限不符每 30s 弹一次（历史「403 风暴」残留面）。修：config 加 silent 选项。
39. ✅ composables/useEnhancedList.ts:65 — queryFn 直接写共享 `total.value` 无代际守卫，快速翻页旧响应覆盖新页 total。
40. ◇ stores/auth.ts:235-248 — Capacitor 链路 token 生命周期断裂：登录写 SecureStorage 但登出从不 removeAccessToken（全仓零调用），request.ts 不组装 Authorization 头；当前 VITE_CAPACITOR 休眠，启用前必须补。

### 由 [H] 降级复核（41-42，阶段 2 探针证据见 §8/§10）
41. ✅ M-41（原 H-2）production_summary_service.py:395-404、403-404 + case/_common.py:38-40 + report_service.py 五处 — naive datetime 比 timestamptz 列（case_movement.py:38 列型亲验）。**实测 `show timezone`=Asia/Shanghai**：当前结果正确，但正确性完全耦合在服务器默认时区上（迁移/新集群默认 UTC 即月窗漂移 −8h）。修：统一 `_BUSINESS_TZ` aware 业务日界，摆脱环境耦合。
42. ✅ M-42（原 H-3）bom_service.py:354、578 + schemas/purchase_center.py:151-159 + product_routes.py:229 — `model_dump()` 无 `exclude_unset`，「键存在才执行」门控被端点层抵消。现网前端全量提交，行为=设计意图；任何省略键的调用方（移动端/脚本/复用方）会静默清空该类 BOM 或全部角色。同族子项：bom_service.py:274-282 明细行部分更新按 `get(name_field,'')` 清空未传字段。修：`model_dump(exclude_unset=True)` 或列表默认 `None` + `is None` 判「未提交」，行内字段同法。

## 5. [L] 发现（31 条）

后端：order_idempotency 表无过期清理；幂等重放响应缺 order_no（endpoints/order.py:347）；order/commands.py:832-834 备份文件事务提交前落盘留孤儿；order_batch_service.py:661 批次号改写不排除已归档；`_invalidate_order_domains` 两份 + `_factory_match` 三份；order_batch_create.py:218 合并订单丢日期；cleanup_orphan 兜底不调 `_reset_uncovered_source_orders`；purchase/_list.py:41-57 has_bom 0 用量口径不一致；purchase_order_crud.py:359 ROUND_HALF_EVEN vs 同文件 ROUND_HALF_UP 约定；purchase_order_crud.py:133-172 合计精度口径；purchase/_list.py:126-129 date_to `'23:59:59'` 闭区间微秒洞；purchase_history/customer_service naive-UTC 展示偏 8h；purchase_plan_crud_ops.py:184-201 delete_plan 无 shipped 禁删守卫；outsource/_shipments.py:322-341 明细顺序相反时 AB-BA 死锁；purchase/_unprocessed.py:340 空真值 has_bom；material_registration/_commands.py:144-147 status 死参数；customer_sampling/common.py:34-39 `_escape_like` 重复实现；roles.py:94-101/pattern_maker_service.py:38-42 check-then-insert 竞态 500；production_summary legacy craft/packaging 无行锁；batch_import_service.py:196-241 ARQ 入口不传 scoped_factory（当前无调用方）；stock_out_service.py:231-259 空白客户串绕过余量校验；stock_inventory_service.py:468 get_inventory 无 factory 参数；stock_in_service.py:276-278 批量备货 500 全回滚不对称；storage_service.py:382-572 DB key 回拼路径无 `..` 防御【门禁盲区】；purchase_utils.py:172-176 float 舍入需变异单测锁定；backup/dump.py:177 未设 PGCLIENTENCODING（GBK 乱码）；policy_service.py:313-321 加密密钥检查死分支假绿灯；backup/schedule_service.py 与 policy_service.py **两套 cron 校验口径相反**（✅亲验：`parse_cron` 与 `_is_valid_cron` 并存）；recovery_test_service.py:623 psql timeout 与 test_timeout_minutes 脱钩；freshness.py:37 裸 mtime 判新鲜度；dump.py:319 db_user 未 isidentifier 白名单。

前端：useStockReturn.ts:159-168 无请求序号；useCustomer.ts:28 死状态；purchase-plan 8 组件 fmt 重复 + 手机号正则两份；OutsourceOrderTab.vue:196 中文文案匹配掉样式；useProductionEntry 数量校验未镜像 int + production_value 浮点尾巴 + refreshTodayCount 失败显示 0；useApproval.ts:104 actionId 单值；request.ts:230-233 去重表误删新条目；stores/auth.ts 登出无跨 Tab 同步；UiInputNumber.vue 死组件+`Number('')`→0 契约坑；useEventDelegation/useVirtualScrollList/realtimeSync.ts 零消费死代码【前端无孤儿门禁】；api/backup.ts:99-107 同步版 15s 假超时；formatQty/formatQuantity/formatNumber 三口径并存 + InventoryTab/ReportTable fmtQty 逐字复制 + MShipmentView fmtQty 漂移；SearchBox↔UiSearchInput、UiProgress 两簇重复组件；MPurchaseView statusLabel 映射缺 confirmed 含幽灵状态；MSearchBar 清空不触发 search；MIncomingView/MProductionView 403 仍显「重试」；useDashboardMobileData fmtNum/fmtMoney 自造；hero 区 axios 英文 message 直出。

## 6. [N] 发现（26 条，全部标注「可不改」）

beile.py float 进 JSON；plan_utils 日期静默钳制；order_batch_create 抵扣文案吞原因；`_assert_orders_generatable` 死代码；`fetch_existing_pending_for_composite_ids` 重抄 `_split_composite_ids`；重名 check-then-act 无 400 映射；`_resolve_pids_from_sku_lines` 同名压缩；幂等重放幽灵订单；综合导入无行级 savepoint；xlsx_budget 注释漂移（42:1 vs 100）；stock_return 400/409 口径不一；manifest zip_size 记明文大小；alert failure_counts 只增不清；nav.py 静态假数据 UTC 日期；dashboard period 自由字符串；staging success 语义（空文件 success=True）；stats.py 工厂收窄整单口径（需裁定）；notification AuditLog 缺操作者；通知轰炸无去重；ocr 识别项无上限；enhanced_pagination 死代码+keyset 缺 tie-breaker；report 导出第二套过滤；mobile 逐行 logger.info；approval int(None)；dashboard float 金额口径；prod_runner 同分支两 print、状态落盘无 fsync、config 注释错位、slow_query except 冗余、双 sanitizer 同名不同义；purchase_center 只读端点用写池；异常字符串判别 400/413；backup 三种时间口径；export_utils `_h` 死代码；productApi 展开合并；errors.ts 英文原文直出；print.ts iframe 残留；beile.ts 硬编码用户名门控；MCard 无 @click、MobileNavBar 死代码、MPurchaseView 非当前页签失败也弹 toast、MProfileView onLogout 无防重入。

## 7. 测试真实性（阶段 3 变异检查定谳）

- **确证 ×2**：`fastapi_app/tests/test_staging.py:588` `test_clear_staging_stockins` 只断言 `mock_db.flush.assert_called_once()`——把 staging/stockin.py:78 的 DELETE 行删掉它仍绿；`test_bad_zip_import_errors.py:32` 期望文案 import 自被测模块，文案内容变异恒绿。
- **可疑 ×4**：test_auth_helpers.py:38（限流通过路径不验 key/计数）、test_backup_m3.py:150（不验 key/值/TTL）、test_cors_origin_production_filter.py:86（同源规则函数自比）、test_product_list_cache_qa.py:369（同一签发实例算期望）。
- skip 统计：pytest skipif 45 + 运行期 skip 12（均带 reason，有元门禁）；vitest skip/todo 0、无断言测试 0。最可疑：contract/qa 类在 CI 无后端时恒跳过，其「绿」不代表验证过。
- 高风险域断言强度：审批/抵扣/备份加密/权限/库存并发 **全部强**（真实 ASGI 403、62 断言零写入校验、独立连接真并发）。整体优于 2026-10-17 基线。

## 8. 性能可疑点（阶段 2 实测数据已回填）

**阶段 2 基准（2026-11-21，只读，erp_system_test，PG 18.3，严格无写操作；脚本 logs/_audit_bench_20261121.py，结果 logs/_audit_bench_20261121_result.json）**：

- `show timezone` = **Asia/Shanghai** → M-41（原 H-2）的月窗漂移当前不发生，正确性耦合在服务器时区配置上（迁移/新集群默认 UTC 即触发）。
- 测试库无业务数据（top 表 n_live_tup=0），B1 用 pg_catalog 回退口径：**单查 0.102ms；200 次逐条 = 20.3ms；批量 ANY($1) 1 次 = 1.13ms；加速 17.9x**。
- B2 推算（静态 SQL 计数 × 实测单查延迟）：stock_event 循环逐单 N=200 ≈ 40.8ms vs 批量版 ≈ 0.3ms；staging 确认 50 行 ≈ 25.5ms（每行 savepoint+balance+status ≈ 5 SQL）。
- 局限声明：业务级前后对比待修复带夹具的回归测试复测；本基准只支撑「模式收益」量级。

### 可疑点清单（供修复排序）

1. [高] stock_event_service.py:56-61 — 循环逐单调 `compute_order_status_from_db`（每单 2 条 SQL），隔壁 `compute_order_statuses_batch`（order_utils.py:72）被绕过。
2. [高] staging/stockout.py:361-364 — 批量确认逐行 savepoint + `get_inventory_balance` + `compute_order_status_from_db`，同产品多行重复算 balance；批量版 `get_inventory_balance_detail_batch`(:458) 只用在 stock_check。
3. [中] auxiliary.py:474-481 — 批量提交逐项 `assert_product_factory_scoped`（产品侧无合并版，订单侧已有）。
4. [中] production_summary_service.py:170-178 — packaging 列表无 limit/分页，year/month 省略全表扫（同模块导出路径有上限，双口径）。
5. [中] outsource/_shipments.py:198-199、383-384 — 循环内逐 process_id `db.get`。
6. [中] batch_import_parser.py:131、188 — sleep 阻塞事件循环（同 M-8）。
7. [中低] stock_out_service.py:94 — FIFO 分摊逐行 `generate_stockout_number`（每行 2-3 往返）。
8. [中低] batch_import_service.py:911 — 导入逐行 `_classify_product_row`。
9. [低] purchase_order_revoke.py:83-90 撤销逐单全明细清理；daily_production_service.py:569/629 循环内逐 pid 锁（有意锁序）；深分页 20+ 处（现页浅可接受）；useSupplierDetailTransform.ts:53 O(n×m)。

## 9. 重复实现对账单（造轮子收网）

| # | 对 | 同形度 | 归一位置 |
|---|---|---|---|
| 1 | `_escape_like`（customer_sampling/common.py:34 ↔ core/sanitizer.py:34） | 完全 | core/sanitizer |
| 2 | `_factory_match` ×3（finished_stock:22 ↔ order_batch:67 ↔ stock_inventory:119） | 近似 | shared/factory_scope |
| 3 | `_invalidate_order_domains`（order/commands.py:74 ↔ order/deduction.py:70） | 完全 | order/_common |
| 4 | `_schedule_post_commit`（canonical=core/domain_events.py:165；副本 product_service.py:42 ↔ purchase_plan_common.py:30）+ **6 处内联绕过**（supplier.py:138,337、user.py:85、customer_sampling/upload.py:122、purchase/_auto_generate.py:83/174/226、purchase_order_revoke.py:368） | 完全 | core/domain_events |
| 5 | 数量格式化：formatQty/formatQuantity/formatNumber 三口径 + InventoryTab:130↔ReportTable:175 逐字复制 + MShipmentView:161 漂移 | 漂移 | utils 双权威 |
| 6 | `response.data.detail` 提取 8 处（canonical=types/errors.ts:28） | 漂移 | getErrorMessage |
| 7 | SearchBox ↔ UiSearchInput | 重复组件 | Ui* 系 |
| 8 | purchase-plan 8 组件 fmt | 完全 | utils/format |
| 9 | cron 校验：schedule_service.parse_cron ↔ policy_service._is_valid_cron（✅亲验并存，口径相反） | 矛盾 | parse_cron 单源 |
| 10 | Excel 导出样板：utils/report_exporter.ReportExporter ↔ 5 处自建 Workbook | 近似 | ReportExporter |
| 11 | printTable（utils/print.ts:76）↔ useBeileOrders/useOutsourceUnshipped 手搭 thead/tbody ×4 | 近似 | printTable |
| 12 | 手机号正则两份（useCustomer.ts:116 ↔ useSupplier.ts:28） | 完全 | utils/validators |
| 13 | assert_product_factory_scoped 逐项 ↔ assert_orders_factory_scoped 批量示范 | 缺批量版 | shared/factory_scope |
| 14 | `services/business_time.py` = core 纯 re-export ✅（无第二实现，安全） | — | 保持 |
| 15 | 根 utils/sanitizer ↔ core/sanitizer 同名不同义（HTML 清洗 vs 日志脱敏） | 改名可消 | 包内别名 |

## 10. 误报记录（亲验撤销）与分级复核

- ~~[H] saveBom 不查复制在途~~：实际 `useProductListActions.ts:479-482` 有 `if (copyInFlight())` 守卫，`useBomQuickCopy.ts:69` 有对称 `isBusy()` 守卫。子代理漏读 479 行。教训：亲验不是形式。
- 分级复核（阶段 2 探针）：原 H-2（naive 比 timestamptz）与原 H-3（save_bom 门控恒真）在当前环境**不产生错误结果**（时区=Asia/Shanghai 实测；前端全量提交），按「什么条件下会错」降级为 **M-41/M-42**；[H] 收敛为 2 条。

## 11. 盲区声明（本次未覆盖，留给后续）

- main.py lifespan 接线、/ws 推送链路（ws-ticket、断线补发）、ocr/_order_parsers.py 前 350 行启发式、cv2.imdecode 无像素上限（潜在解码炸弹）。
- server_manager/app.py 1600 行 GUI 仅抽查；backup_encryption chunked-v1 读侧只速读。
- vitest 侧断言强度未深读（只做了 skip/无断言普查）；同类/在线契约测试在 CI 恒跳过，其语义只在本生产机验证过。
- purchase_order_query.py 部分、_factory.py 1-420 仅速读；前端 156+152 文件中约 60 个小组件仅 grep 扫过。
- PG 会话时区未实测（H-2/M-26 结论以此为准，阶段 2 顺带确认）。

## 12. 修复计划（阶段 3 输入）

1. 顺序：H（4）→ M（40）→ L（31）→ N（26），一个不留；每修复 Red→Green 配回归测试，假测试 6 条一并修（先变异确认再改断言）。
2. 家族修法优先：失败空态族（7 处）统一抽「错误横幅+重试」模式对齐 beile 样例；dashboard 吞异常族统一 503 口径；naive-vs-timestamptz 族（H-2/M-3/M-26）统一 `_BUSINESS_TZ`/business_day_bounds；403 静默豁免 + deferred 下沉共享层。
3. 造轮子对账按 §9 归一（每归一一处跑聚焦测试）。
4. 阶段 2 基准点：§8 的 1/2/3/4 号（stock_event 批量版切换、staging 批量确认、factory gate 批量版、packaging 上限），只读连 erp_system_test，产出前后对比。
5. 全部修复完成后：提权单实例全量 pytest + CI 三 job 本地等价 + review_packet + 等 owner 说「推送」。

## 13. 修复台账（阶段 3 实际执行，2026-11-21）

分支 `fix/audit-full-20261121`（基于 main @ c44478e2），22 个提交。每单元 Red→Green + 邻居套件 + quality_gate 回基线。

### 13.1 修复单元（按提交序）

| # | 提交 | 内容 | 级别 |
|---|---|---|---|
| 1 | 6ea0aa57 | 导入数量小数截断 ×4 处收敛唯一实现 | H-1 |
| 2 | 54d44e2e | factories 跨厂泄漏（owner 裁定：items 全量=设计意图，只修 factories） | H-2 |
| 3 | c3cebd5b | 时区族：aware 日界 + 显式分桶；批次历史日期筛选必 500（实跑升级 H） | M-41/M-26/M-3↑H |
| 4 | d2102809 | DB 连接异常全局 503 + dashboard 五 service 停吞（×7 站点） | M-16 族 |
| 5 | f8dc3676 | 计划状态白名单+Literal+行锁；审批列表 Literal | M-6/M-11/L |
| 6 | d44e027a | 手工采购单幂等键（实测复现重复建单：同键第二次真建 id=2） | M-28 |
| 7 | 2dce0464 | 备份五连：演练假失败/原子落盘×3/JSON 导出互斥/legacy 信封 unverified/流式计数 | M-19/20/21/27/29 |
| 8 | 431e67b3 | staging APPROVED 死行清理×3 域 + InventoryLog 前后结存×4 站点 | M-13/M-14 |
| 9 | e5de705a | OCR 数量封顶防 500 + 客户改写留痕 | M-25/M-24 |
| 10 | 2ef78a45 | token_version 跨 worker 广播（复用 USER_PERMISSION_CHANGED 事件链） | M-23 |
| 11 | e20023f1 | 非法日期 400/显式 null 500/无界列表 max_length/sleep 出事件循环 | M-15/10/18/8 |
| 12 | 407f6464 | 单价 Decimal 单源（schema+双实现合一）+ 审批编辑补工厂通知 | M-17/M-22 |
| 13 | 877abc21 | 整单/明细改量数量下限守卫 + 批量下单抵扣量按实扣回写 | M-2/M-1 |
| 14 | 73f04813 | cleanup JSON 兜底歧义守卫 + 计划重算 handler 失败落死信 | M-4/M-5 |
| 15 | 678ce985 | BOM 行键存在才写 + 皮套导出超限 413 + 已收货登记禁删 | M-7/M-9/M-12 |
| 16 | c1a835cc | 性能：stock_event 批量版切换 + staging 结余批预取/行间递减（SQL 计数回归防回退） | 性能双修 |
| 17 | 32095621 | 前端五小修：跨类型导入丢行/task_id 兜底/beile 权限前置/报告排序移除/total 代际 | M-30/34/35/36/39 |
| 18 | 000b6580 | 失败空态族×7 诚实化（错误态+重试）+ 仪表盘趋势图去假数据（改「今日订单」） | M-33 族/M-32 |
| 19 | ed8917ba | deferred 下沉共享层 + 403 请求级静默豁免 + Capacitor 登出清 token | M-37/38/40 |
| 20 | f14d8aea | 外发发货/计划创建提交函数级重入闸 | M-31 |
| 21 | 02bbc262 | 假测试 6 条加固（2 确证 + 4 可疑，变异检查口径） | X-T |
| 22 | d1563a49 | L/N 第一波：采购/订单/备份/平台域 48 文件（造轮子收编 schedule_post_commit 六处内联 + 兼容别名） | L×20+/N×10+ |

### 13.2 验证证据

- 每单元：真 Red（stash 复跑/前置校准）→ Green → 邻居套件（§13.1 各提交信息含数字）。
- 假测试：六文件 139 passed（02bbc262）。
- L/N 第一波：346 passed 全邻居（d1563a49 提交信息）+ quality_gate PASS（仅 TIGHTEN 项，语义门禁累计 -1）。
- 语义门禁自动收紧 1 处：建单幂等缺口被 M-28 修复记账（45/46）。
- bandit 自动收紧 1 处：20→19。

### 13.3 流程外收获

- M-3 实跑升级 [H]（asyncpg 下 timestamp >= varchar 直接 500——静态审计只判了时区错位）。
- M-28 实测复现 Bug 本体（幂等重放永不命中 → 重复建单）——根因是 result 无 success 键。
- 门禁抓出 3 次修复引入的函数超长（M-19/拆 helper 恢复、M-4/抽 _json_contains_trusted、M-7/walrus 合并）——基线棘轮反向发挥了作用。
- 亲验撤销子代理 1 条误报（saveBom 并发——实际有 copyInFlight 守卫）。
- 阶段 2 时区探针（show timezone=Asia/Shanghai）促成 2 条 H→M 降级，分级口径回归「什么条件下会错」。

### 13.4 未竟事项（诚实记录）

- L/N 余量：前端 26 条由清扫代理处理中（完成后另行提交）；注释化处理条目（stats 工厂口径、backup_progress base64、float 金额口径等）已标「等 owner 裁定」，非行为修复。
- report_service 导出第二套过滤的双向漂移面：已加注释未强行合并（合并属结构改造，超出定点修复边界）。

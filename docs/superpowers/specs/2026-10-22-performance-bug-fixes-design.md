# 2026-10-22 性能与缺陷修复 — 设计规格

> 状态：待评审
> 来源：`docs/reviews/2026-10-22-performance-and-bug-review.md`（下称"原报告"）
> 范围口径：按核实后的真实缺陷全修；原报告中不属实/刻意设计的条目按核实结论处理。
> 约束：本机即生产机，无独立测试环境；改动小步、可回滚；提交前跑门禁。

## 1. 背景与目标

原报告列 39 条发现。逐条取证后：29 条属实、8 条部分属实、1 条不属实（M13）、1 条刻意设计（L6）。本规格把"值得修的真实缺陷"拆成 4 批，明确每条的现状证据、修复方案、验收标准与回滚路径。

目标：
1. 消除当前正在发生的正确性缺陷（M5、M6）。
2. 把阻塞事件循环的 CPU/IO 操作下沉，避免随数据增长演变为停摆。
3. 补齐可靠性缺口（降级上报、任务幂等、撤销广播、审计兜底、漏跑补跑）。
4. 修正原报告中会误导后续排期的错误结论。

## 2. 范围决策（已确认）

| 决策 | 结论 |
|---|---|
| 修复范围 | 按核实后的真实缺陷全修 |
| M5/M6 行为变更 | 先只读评估影响，再决定（已完成，见 §3） |
| M6 历史回填 | **补跑**缺失日期 |
| M1 生产开关 | **在生产 `.env` 设 `CACHE_L1_BROADCAST_ENABLED=true` 并重启** |
| 部署 | 本轮只改代码并提交；重启生产需 owner 明确发话，且工作区必须在 main |
| M13 | **删除无调用的死配置**，不加截断告警 |
| L6 | **保留**（刻意 fail-safe 设计），只在代码注释/规格中记录 |
| 交付方式 | 单一修复分支 + 4 批提交；推送前一次新眼睛评审 |

## 3. 只读影响评估结果（已实测）

### 3.1 M5 工厂隔离

- 厂绑定非超管用户 7 人（东莞 6、湖北 1）。
- 其中 **2 人持有 `order_manage`**（段地香、周秋霞，东莞）→ 漏洞**可达**。
- 厂绑定用户创建过的订单：**0 条**（`inventory_log` 按 `operator_id` 关联）→ 加闸门**不破坏现有业务**。

### 3.2 M6 出货同步

- `shipment_records` **全表 0 行**。
- 生产日志证实：2026-10-22 01:00 同步的是 `2026-10-20`（应为 10-21）。
- 近 14 天有出货的 7 天（10-08/10/12/14/15/16/17）均未同步。
- 结论：不是"未来隐患"，而是**该功能从未成功工作过**；修复必须同时补跑历史窗口。

## 4. 批次 A — 正确性与可靠性（无行为变更）

### A0 / 原报告 §〇 已核实为健康（无动作）

| 旧结论 | 核实 |
|---|---|
| `pool_recycle` 未设置 | 不成立：`database.py:95-98` 已有 1500 + pre_ping + LIFO，且有守卫测试 |
| prod_runner 假成功 | 已修复：`_FrontendNginx` 已删、探针校验 `"service":"nginx"`、stderr 落盘 |
| gzip 压缩真空 | 已修复：默认恒开，仅 `APP_GZIP_DISABLED` 关闸 |
| PWA SW 接管 API | 已修复：API 为 `NetworkOnly`、`navigateFallback: null` |

### A1 / H4 安全降级登记机制成孤儿

**现状**：`core/middleware.py:53-64` 定义 `record_degradation`/`degraded_reasons`；全仓无生产调用；`core/health.py:81-91` 的 `security_degraded` 恒为 false。

**修复**：
1. 在以下 fail-open 降级点接入 `record_degradation`：
   - CSRF 校验因配置缺失而放行；
   - 黑名单查询 Redis 异常且 `fail_closed=False`；
   - 维护模式检查异常时放行。
   （备份加密总开关关闭时忽略 `encrypt=true` 是文档化的产品默认行为，不计入"降级"。）
2. `degraded_reasons()` 改为可跨 worker 观测：在 `/api/health` 汇总时同时读取 Redis 键 `security_degraded:<worker_pid>` 的并集（TTL 与心跳一致），避免 8 worker 各报各的。
3. 保留进程内列表作为单 worker/测试路径。

**验收**：
- 新增测试：模拟 Redis 异常 + `fail_closed=False` 的撤销查询，断言 `degraded_reasons()` 含对应 reason，且 health 响应 `security_degraded=true`。
- 测试：正常路径 `security_degraded=false`。
- 变异检查：注释掉接线，对应测试必须变红。

### A2 / M8 批量计划导入缺幂等

**现状**：`tasks/plan_tasks.py:92` 每次尝试重新生成 `batch_id`；全文件无 `job_idempotency`。对照 `tasks/batch_tasks.py:302-305` 的标准做法。

**修复**：
- 用 `job_idempotency(ctx, namespace=IDEMPOTENCY_NAMESPACE_BATCH_IMPORT)` 包住写库段；
- `batch_id` 由 `job_id + file fingerprint` 派生，落库前先查该 `batch_id` 是否已存在；
- **本轮不加数据库唯一约束**（存量重复情况未核实，迁移只做结构变更且需单 head）；靠幂等键 + 前置查询防重。

**验收**：
- 新增测试：同一 job 重放两次，`production_plan` 行数不变、返回同一 `batch_id`。
- 变异检查：移除 idempotency，测试变红。

### A3 / M2 采购单撤销 N+1

**现状**：`services/purchase_order_revoke.py:57-58` 循环内逐单调 `compute_order_status_from_db`，每单 2+ 条 SQL。

**修复**：新增 `compute_order_statuses_batch(db, order_ids)`，一次 `IN (...)` 聚合；循环外调用。保持单条函数供其他调用方使用。

**验收**：
- 现有撤销测试全绿；
- 新增测试：N 单撤销时 SQL 次数不随 N 线性增长（用 SQLAlchemy event 计数）；
- 结果与旧实现逐单比对一致。

### A4 / M3 外协状态筛选全表扫描

**现状**：`services/outsource/_queries.py:102-113`，仅在传 `process_status` 时全量进内存再 Python 过滤。

**修复**：把进度聚合与状态过滤下推为 SQL 子查询/JOIN，保留分页在 SQL 侧；无 `process_status` 的分支不变。

**验收**：
- 现有外协筛选测试全绿；
- 新增测试：大数据量下返回结果与旧实现一致；
- 查询计划不含全表扫描（可选，记录 `EXPLAIN`）。

### A5 / M4 图片上传同步 PIL 解码

**现状**：`api/v1/endpoints/customer_sampling.py:241` → `services/customer_sampling/upload.py:59-63` 同步 `Image.open().verify()`。

**修复**：`await asyncio.to_thread(svc.validate_project_image, content, ...)`。

**验收**：
- 现有上传测试全绿；
- 新增测试：校验期间事件循环可继续调度（用一个 `asyncio.sleep(0)` 探针断言并发度）。

### A6 / M9 token 撤销跨 worker 失效

**现状**：`core/auth/blacklist.py:61-81` 登出 jti 只写当前 worker LRU；Redis 正常时也写 Redis；故障期其他 worker 放行（`fail_closed=False`）。

**修复**：
1. 登出时发布 pub/sub 事件（复用缓存广播的 Redis 客户端与重连退避模式），各 worker 监听并写入本地 LRU；
2. 保留 Redis 键作为权威；监听器断线重连后从 Redis 补拉最近撤销集合；
3. **`fail_closed` 保持 False**：Redis 抖动时改 True 会误杀在线用户；改为通过 A1 的降级登记把"故障期放行"变成可观测告警。是否在将来收紧为 True 属独立决策，本轮不做。

**验收**：
- 新增测试：worker A 登出后，worker B 的 `is_token_revoked` 返回 True；
- 新增测试：Redis 故障 + `fail_closed=True` 时拒绝；
- 变异检查：移除广播，跨 worker 测试变红。

### A7 / M10 审计日志双故障静默丢

**现状**：`core/audit_middleware.py:408-446` 直写失败仅 warning；`:313-336` Redis 失败兜底忽略返回值。

**修复**：
1. 新增 Prometheus Counter `audit_write_failures_total{stage="redis|db"}`；
2. 直写失败时追加到本地溢出文件 `logs/audit_overflow.jsonl`（单行 JSON，受日志清理策略管理）；
3. 启动/定时任务尝试回灌溢出文件（幂等：按 `request_id` 去重）。

**验收**：
- 新增测试：模拟 DB 失败，断言指标 +1 且溢出文件有记录；
- 新增测试：回灌后审计表有记录且不重复；
- 溢出文件纳入 `utils/log_rotation` 的清理范围。

### A8 / M11 `safe_publish_event` 吞异常

**现状**：`core/exception_handler.py:96-101` 全吞且 `exc_info=False`。

**修复**：编程错误（非基础设施异常）用 `logger.exception` 保留堆栈；基础设施异常保持 warning 但带上异常类型；事件发布失败计数。

**验收**：
- 新增测试：注入 `TypeError`，断言日志含 traceback（用 caplog）；
- 现有异常处理测试全绿。

### A9 / M12 大上传内存累积

**现状**：`core/middleware.py:461-471` 无 Content-Length 时全量累积后 `b"".join`；上限 512MB。

**修复**：
1. 无 Content-Length 时改用 `tempfile.SpooledTemporaryFile(max_size=8MB)` 累积，超阈值落盘；
2. 备份上传端点改为 `request.stream()` 直接写临时文件（需逐个确认端点，避免破坏现有 `request.body()` 语义）；
3. 超过 `MAX_BACKUP_UPLOAD_BYTES` 立即 413，不再先收完再判。

**验收**：
- 新增测试：无 Content-Length 的 100MB 流式上传，进程 RSS 峰值不随体积线性增长（用 tracemalloc/进程内存采样）；
- 现有上传/备份测试全绿；
- 413 路径测试。

### A10 / M7 ARQ 日级 cron 停机漏跑

**现状**：`core/arq_app.py:256-315` 中 `sync-shipment-daily`（01:00）、`log-maintenance`（04:30）是日级 cron；worker 停机跨越触发点即永久漏跑。备份调度**不在此列**——`schedule_service.due_schedules` 已按过期窗口补跑，原报告"备份错过 12 个扫描点"不成立。

**修复**：
1. 在 Redis 记录每个日级 cron 的最近成功日期（键 `cron_last_ok:<name>`，由任务成功回调写入）；
2. worker 启动时与每 10 分钟巡检一次：若"今日应跑时刻已过"且"今日未成功"→ 幂等入队一次（job id 含 name+date）；
3. 仅覆盖日级 cron；每 5/10 分钟的周期任务天然自愈，不处理。

**验收**：
- 新增测试：模拟昨日成功、今日未跑且已过时刻 → 启动后入队一次；重复启动不重复入队；
- 新增测试：今日已成功 → 不入队；
- 现有 ARQ 测试全绿。

## 5. 批次 B — 性能与资源（无行为变更）

### B1 / H1 备份 CPU/IO 同步阻塞事件循环

**现状**：
- `services/backup/orchestration/core.py:585` 在 async 函数内同步调 `_encrypt_backup`；
- `_pack_backup_zip`（`:436-451`）是 async 但同步写 ZIP；
- `:559` `sha256_file` 同步；
- `recovery_test_service.py:594-612` 同步 `gzip.read()` + `subprocess.run(psql, timeout=600)`，在 ARQ 任务内执行；
- `orchestrator.py:276` 整包解密同步。

**实测**：当前备份 65–68MB，加密耗时 **1.3s**（chunked 默认）/ 0.5s（legacy），不是原报告所称"数十秒/GB 级"。

**修复**：
1. `_encrypt_backup` 调用改为 `await asyncio.to_thread(...)`；
2. `_pack_backup_zip` 的 ZIP 写入段整体下沉线程池；
3. `sha256_file` 改 `await asyncio.to_thread(sha256_file, ...)`；
4. `recovery_test_service` 的 `gzip.read()` 与 `subprocess.run` 改用已有的 `services/backup/_proc.py` 封装；
5. `orchestrator._decrypt` 改 `await asyncio.to_thread(...)`；
6. 不改变 API 端点语义（本轮不做"入队 ARQ"改造，避免接口变更）。

**验收**：
- 新增测试：备份加密期间事件循环可调度（探针协程在 to_thread 期间推进）；
- 现有备份/恢复测试全绿；
- 基准记录：68MB 加密仍约 1.3s，但不再阻塞循环。

### B2 / H2 JSON 备份内存放大

**现状**：`services/backup/json_backup.py:336-345` 逐表 `SELECT *` 无上限 + `indent=2`；`api/v1/endpoints/backup/export.py:112` 请求内执行。

**修复**：
1. 逐表分批 `yield_per` 流式写临时文件，避免整库 `json.dumps`；
2. 去掉 `indent=2`（或仅在调试开关下保留）；
3. 端点改为流式响应（`StreamingResponse` 读临时文件）。

**验收**：
- 新增测试：导出的 JSON 可被现有恢复逻辑读取；
- 内存峰值测试：大表下不随全库体积线性增长；
- 现有导出/恢复测试全绿。

### B3 / H3 多 worker 日志轮转竞态

**现状**：`core/logger.py:64-76` 每个进程一个 `TimedRotatingFileHandler`，同一文件、同一 `backupCount=14`。实测当前轮转产物正常、无 `Logging error`，影响未观测到，但机制成立。

**修复**：
- 改用普通 `FileHandler`（追加），移除进程内午夜轮转；
- 轮转统一交给已有的外部 copytruncate：`utils/log_rotation.rotate_oversized_logs`（`prod_runner._rotate_logs_if_due` 已周期调用，ARQ 每日兜底）；
- 保留现有文件名 `fastapi_YYYYMMDD.log`，避免破坏 Loki/Promtail 采集规则。

**验收**：
- 新增测试：多进程同时写同一日志文件，轮转后无异常、无日志丢失（用临时目录）；
- 现有日志测试全绿；
- 生产验证：轮转产物由外部任务生成。

### B4 / M1 L1 缓存广播关闭

**现状**：`core/cache.py:72` 默认 false；`:457-458` 有开关；监听器完整；`services/order/queries.py:241-245` 因无广播而 `local_ttl=0`。

**修复**：
1. 生产 `.env` 设 `CACHE_L1_BROADCAST_ENABLED=true`（运行期变更，见 §8）；
2. 恢复订单列表 `local_ttl`（建议 30s），其余热路径按实测收益逐个恢复；
3. 启动时校验：多 worker + 广播关闭 → 记录 warning（帮助发现配置回退）。

**验收**：
- 新增测试：worker A 失效缓存后，worker B 的 L1 命中被清除（用假 Redis pubsub）；
- 订单列表缓存测试：TTL 生效且失效后立即回源；
- 生产验证：开广播后订单列表 P95 延迟不升。

### B5 / L3 限流 Redis 未配置回退 memory

**现状**：`core/limiter.py:78-86` 回退 `memory://`，多 worker 阈值放大 8 倍。

**修复**：生产环境启动时若 `REDIS_CACHE_URL` 缺失 → fail-fast（与现有 `STRICT_CONFIG_CHECK` 口径一致）；非生产保留回退并打 warning。

**验收**：
- 新增测试：生产 + 缺失 URL → 启动失败；开发 → 回退且 warning。

### B6 / L10 双 ARQ worker 风险

**现状**：`core/prod_runner.py:820` `with_arq = "--no-arq" not in argv`；当前 NSSM 命令含 `--no-arq`，未触发。

**修复**：增加显式外部 ARQ 标记（如 `ERP_ARQ_EXTERNAL=1`）或检测 `erp-arq` 服务存在；命中时即使未传 `--no-arq` 也不启动内置 ARQ，并记录 warning。

**验收**：
- 新增测试：环境变量置位时 `with_arq=False`；
- 现有 prod_runner 测试全绿。

### B7 / L15 Redis 大 value 同步序列化

**现状**：`utils/redis_cache.py:294,314` 在 async 方法内同步 `json.loads/dumps`；池 `max_connections=100`。

**修复**：大 value（> 阈值，如 64KB）改 `await asyncio.to_thread(json.dumps/loads, ...)`；小 value 保持同步（避免线程池开销）。
**不修**：原报告"接近 Windows Redis maxclients"不成立（实测 `maxclients 10000`）。

**验收**：
- 新增测试：大 value 序列化期间事件循环可调度；
- 现有缓存测试全绿。

### B8 / L16 备份覆盖度逐表 COUNT

**现状**：`orchestration/core.py:232-251` 的 `_count_tables` 逐表 `COUNT(*)`；原报告行号 546-549 指向的是查表名，非 COUNT。

**修复**：改用 `pg_class.reltuples` 估算（大表不锁），仅对 manifest 标记为估算值；小表或需要精确值时保留 COUNT（按表体积阈值切换）。

**验收**：
- 现有备份 manifest 测试全绿；
- 新增测试：估算值与真实值偏差在可接受范围（记录，不硬断言）。

## 6. 批次 C — 行为修正

### C1 / M5 订单创建工厂闸门

**现状**：`api/v1/endpoints/order.py:312-316` 单条创建、`auxiliary.py:451-461` 批量创建均无工厂校验；编辑/删除有 `_assert_order_factory_scoped`。评估：2 名厂绑定用户持有 `order_manage`，但历史跨厂订单 0 条。

**修复**：
1. 单条创建：调用前 `await assert_product_factory_scoped(db, data.product_id, user, what='产品')`；
2. 批量创建：逐项校验，任一越权整批拒绝（与库存批量端点口径一致）；
3. 与编辑/删除保持同一错误语义（404，不暴露存在性）。

**验收**：
- 新增测试：厂绑定用户对异厂产品下单 → 404；
- 新增测试：本厂产品 → 成功；
- 新增测试：超管/未绑定用户不受影响；
- 现有订单创建测试全绿。

### C2 / M6 出货同步时区 + 补跑 + 历史回填

**现状**：`tasks/plan_tasks.py:38-39` 用 `datetime.now(UTC).date() - 1`；arq cron 按系统时区（CST）在 01:00 触发 → 实际同步"前天"；`shipment_records` 全表 0 行；docstring 声称刷新 `purchase_plan_details.shipped_qty` 但代码未实现。

**修复**：
1. 日期口径改为 `business_today() - timedelta(days=1)`；
2. 任务改为**回看窗口**（默认 3 天，可配置），对窗口内每天幂等 upsert（按 `shipment_no`），自然补上漏跑；
3. 删除 docstring 中"并刷新 `purchase_plan_details.shipped_qty` 缓存"的失实描述——该逻辑当前不存在，`shipped_qty` 刷新属独立功能，本轮不实现；
4. **一次性历史回填**：对 2026-10-08～2026-10-21 运行同一同步逻辑（幂等），执行前备份目标表。

**验收**：
- 新增测试：固定时钟为 CST 01:00，断言目标日期 = 业务昨日；
- 新增测试：窗口内多日数据均被同步且重复运行不产生重复行；
- 回填后只读核验：`shipment_records` 行数与 `stock_out` 对应日期的有效行一致；
- 回填前后 `shipment_records` 计数记录在案。

### C3 / M13 删除无调用死配置

**现状**：`frontend-vite/src/stores/catalog.ts:21` `per_page: 1000`；后端三处 `le=200` → 传 1000 会 422；`ensureProducts/ensureCustomers/ensureSuppliers` 无生产调用方。
**核实结论**：原报告"静默截断导致下拉缺项"**不属实**。

**修复**：删除未使用的 catalog 条目与 `CATALOG_PAGE_PARAMS`（保留 `ensureActiveCustomerNames` 及其轻量端点）；若后续需要全量下拉，改用轻量端点 + 分页。

**验收**：
- 前端 type-check / lint / 单测全绿；
- 全仓 grep 无残留引用；
- 相关下拉页面手工验证（客户名下拉仍正常）。

### C4 / M14 PrimeVue 安装时序

**现状**：`src/main.ts:108` 先 `app.mount`，`:120-148` 异步安装 PrimeVue。

**修复**：把 PrimeVue 安装改为 `await import(...)` 后再 `app.mount`；启动期间显示现有 loading（若有）。

**验收**：
- 新增单测：mount 前 `app.config.globalProperties.$primevue` 已存在；
- 手工验证：首屏弹层 z-index/locale 正常；
- type-check / lint 全绿。

### C5 / M15 AutoComplete 虚拟滚动

**现状**：`components/ui/UiAutocomplete.vue:279-301` 未传 `virtualScrollerOptions`；数据量封顶 200。

**修复**：传 `virtualScrollerOptions`（itemSize 与当前行高一致），保持现有交互不变。

**验收**：
- 组件单测全绿；
- 手工验证：出库/下单页下拉可滚动、键盘导航正常。

### C6 / L11 SW 预缓存体积

**现状**：`vite.config.ts:86` `globPatterns` 收录全部构建产物（含懒加载路由 chunk）。

**修复**：设置 `maximumFileSizeToCacheInBytes`（如 2MB），对超大 chunk 改用 runtime caching（`StaleWhileRevalidate`），避免首装带宽尖峰。

**验收**：
- 构建产物中预缓存清单体积下降（记录前后值）；
- 离线/更新流程手工验证；
- `npm run build:atomic` 成功。

### C7 / L12 可编辑行 `:key="idx"`

**现状**：`DialogRoleEditor.vue:3-15`、`ShipmentPlanControl.vue:15` 用索引作 key + splice 删除。

**修复**：为行数据引入稳定 id（前端临时 uuid），`v-model` 绑定按 id 定位；删除按 id 过滤。

**验收**：
- 组件单测：删除中间行后剩余行值与输入焦点正确；
- 手工验证：中文 IME 组合态不错位。

### C8 / L13 请求取消

**现状**：`src/api/request.ts` 无 `AbortController`；有 GET 去重。

**修复**：request 层支持可选 `signal`；路由切换时 abort 上一路由的未完成请求（全局 router hook）；保留去重逻辑。

**验收**：
- 新增单测：切换路由后旧请求被 abort，不产生错误提示；
- 现有请求测试全绿。

### C9 / L14 console.error 吞错范围

**现状**：`src/main.ts:18-31` 按子串吞 `console.error`，仅首个参数为 string 时生效。

**修复**：把抑制规则收窄为精确匹配已知噪音（保留 `Error` 对象不被吞），并在开发环境不抑制。

**验收**：
- 新增单测：`Error` 对象始终输出；已知噪音被抑制；
- 手工验证：控制台噪音未增加。

## 7. 批次 D — 低危收口与文档

| 编号 | 现状 | 修复 | 验收 |
|---|---|---|---|
| D1 / L1 | `daily_production_service.py:393,634,642,712` Decimal→float→round | 全程 Decimal，仅展示层转 float | 金额计算单测逐值比对 |
| D2 / L2 | 裸 `datetime.now()` 做文件名/时间戳 | DB 字段用 aware UTC；文件名显式用本地时间并注释；不改变现有文件名格式 | 相关测试 + 文件名解析测试 |
| D3 / L4 | `health.py:365-372` `startswith` 比较 | 改 `hmac.compare_digest` | 单测：前缀不匹配被拒 |
| D4 / L5 | `config.py:296-298,343-346` import 期固化 | CORS/DOCS 移入 `create_app()` 统一求值 | 启动测试：运行时环境与配置一致 |
| D5 / L7 | `metrics.py:48-80` 私有属性 | 改公开 API 或维护自有映射 | metrics 单测全绿 |
| D6 / L8 | `config.py:343` 开发 CORS 含 `null` | 移除 `null` 源 | 配置单测 |
| D7 / L9 | `token.py:15-46` 签名密钥缓存永不过期 | 加 TTL（如 300s）或版本键 | 密钥轮换测试：无需重启即可生效 |
| D8 / L6 | `sanitize_error` 与生产闸门不同源 | **保留**，在 docstring 标注刻意 fail-safe | 无代码变更，仅文档 |
| D9 | 原报告错误结论 | 在 `docs/reviews/2026-10-22-performance-and-bug-review.md` 顶部加勘误表（M13/H3/M7/L15/量级） | 文档审阅 |

## 8. 运行期变更（需 owner 明确发话）

### 8.1 M1 开启 L1 广播

1. 确认工作区在 `main`（`git rev-parse --abbrev-ref HEAD`）。
2. 编辑生产 `.env`：`CACHE_L1_BROADCAST_ENABLED=true`。
3. 重启 `erp-prod`（必须提权；`nssm restart erp-prod`）。
4. 验证：`logs/prod_runner.json` 的 `workers=8` 且 `ready=true`；确认新 PID 的 CreationDate 更新；抽查订单列表缓存失效行为。

### 8.2 M6 历史回填

1. 先备份 `shipment_records`（当前为空，备份成本可忽略）。
2. 以只读方式复核 10-08～10-21 的 `stock_out` 有效行数。
3. 运行幂等同步（窗口模式），记录写入行数。
4. 复核：`shipment_records` 按日期计数与 `stock_out` 一致；重复运行不新增行。

## 9. 验证与交付

1. 每批：聚焦测试 + 对应 `check:*`。
2. 全部完成：提权全量 `pytest`（`logs/_run_pytest_elevated.ps1`）+ `ruff` + `mypy` + 前端 `type-check/test/lint/check:*`。
3. 推送前：`python scripts/review_packet.py` → 新眼睛评审（最强模型）→ 零 High/Medium。
4. 提交：一批一个主题提交，只 `git add` 本批文件；提交信息写"为什么"。
5. 不重启生产，除非 owner 明确发话。

## 10. 明确不做

| 项 | 原因 |
|---|---|
| M13 加"截断告警" | 原结论不属实；死配置应删除 |
| L6 统一 `sanitize_error` 判定 | 刻意 fail-safe，统一反而增加泄露风险 |
| H1 "API 端点改入队 ARQ" | 接口变更大、收益在 1.3s 量级下不成立；本轮只做线程池下沉 |
| 备份文件名格式变更 | 历史教训：文件名解析有多个消费点 |
| 生产库 `alembic autogenerate` | 项目红线 |
| 任何 `0.0.0.0` 绑定/删除 `utils` 等红线操作 | AGENTS.md §5 |

## 11. 风险与回滚

| 风险 | 缓解 |
|---|---|
| M5 误拦现有流程 | 评估已证实 0 条受影响订单；上线后观察 404 日志 |
| M6 回填写错日期 | 先只读核对；按 `shipment_no` 幂等；先备份 |
| A9 上传改造破坏端点 | 逐端点确认 `request.body()` 用法；保留旧路径开关 |
| B3 日志改造影响采集 | 文件名不变；仅移除进程内轮转 |
| M1 广播增加 Redis 连接 | 8 条 pubsub 连接，远低于 maxclients 10000 |
| 批量改动引入回归 | 分批提交、每批独立回滚、推送前全量门禁 |

回滚：每批一个 commit，`git revert <sha>` 即可；运行期变更（M1）回滚为改回 `false` 并重启。

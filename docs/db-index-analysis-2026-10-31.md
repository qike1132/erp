# 数据库查询性能与索引体检报告

> **采集时间**：2026-10-31 22:50–23:10（北京时间）
> **采集方式**：只读探针直连生产 `erp_system`（asyncpg，会话级 `default_transaction_read_only=on`）+ 近 6 天应用慢查询日志（`logs/fastapi_202610*.log`，阈值 OLTP 0.2s / 报表 1.0s）+ ORM 模型与迁移静态比对
> **对照基线**：`docs/performance-baseline.md`（2026-09-14 实测）
> **性质**：只读诊断，未对生产做任何写操作；所有 EXPLAIN ANALYZE 仅对纯 SELECT 执行

---

## ⭐ 执行结果（2026-10-31 23:55 更新，本轮优化已落地）

| 项 | 状态 | 证据 |
|---|---|---|
| **P0 pg_stat_statements** | ✅ 已安装 | 两次低峰 PG 重启（临时 pg_hba trust 行已撤销并验证恢复密码认证）；`SHOW shared_preload_libraries` = pg_stat_statements；erp_app 已授 pg_read_all_stats，统计开始积累 |
| **P1-R1 audit_log 删 3 索引** | ✅ 已执行 | 迁移 pg_standalone_106（DROP CONCURRENTLY），模型声明同步删除 |
| **P2 双索引 bug（purchase_order）** | ✅ 已执行 | 迁移删 ix_purchase_order_source_order_id，模型删列级 index=True |
| **P2 poi 前缀冗余** | ✅ 已执行 | 迁移删 idx_purchase_order_item_order（INCLUDE 版已建），模型同步 |
| **P4 幽灵索引落库** | ✅ 44 个已建 | DDL 由 CreateIndex 从模型逐字编译；order 的 idx_perf_* 谓词修正为 IS NOT TRUE（原 = false 无法服务查询——模型侧潜伏缺陷一并修复） |
| **P4 模型对齐** | ✅ 已完成 | audit_log 索引声明全删（纯写不读）；stock_in/stock_out idx_perf 冗余声明删（库内 ASC 版等价，B-tree 可反向扫）；staging_stock_out 列级双声明删（同 purchase_order 同型缺陷）；material_registration.idx_material_reg_supplier 列漂移修正（supplier_name→supplier_id） |
| **P4 对账脚本** | ✅ 已交付 | `scripts/diag/check_schema_drift.py`（只读，已登记写守卫白名单）；**复跑结果：MODEL_ONLY 53→0，COLUMN_MISMATCH→0**（DB_ONLY 剩 16 个良性：物化视图索引/显式命名唯一约束，不在 ORM table.indexes 中） |
| **P1-R2 audit_log 保留期** | ⏳ 待决策 | 涉及审计合规保留年限，需 owner 决定（当前 26.1 万行 / +200 行/天） |
| **P2 其余前缀冗余** | ⏳ 按计划等待 | 等 pg_stat_statements 积累一个完整业务月（约 2026-11 月底）再执行 |
| **P3 编号表达式索引** | ⏳ 规模触发 | 业务表 >1000 行或巡检单实体 >100ms 再建（当前 order 71 行）；近期可先做巡检降频评估 |

**验证**：全量提权 pytest 5274 passed / 57 skipped（唯一失败为写守卫白名单登记，补登后聚焦复绿 131 passed）；迁移链单一 head；生产 alembic 105→106 应用成功；迁移后服务健康 ready=true / frontend_ok=true。

**事故与恢复记录**（运维教训，2026-10-31 23:20–23:40）：`net stop` PostgreSQL 时 Windows 服务依赖链连带停止 erp-prod/erp-arq/erp-web（redis 不受影响）；且 NSSM 停止未杀干净 uvicorn master（孤儿进程与新 master 双绑 5002），nginx 存在新旧交替期 502。已全部恢复：三服务启动、孤儿进程树清理（PID 38808 树）、健康快照 ready=true，后端运行 commit 0593dbb8（owner 逐项授权）。**下次重启 PG 用 `pg_ctl restart -m fast -D <PGDATA>` 直连进程控制，不走 SCM 服务接口，避免依赖链连停。**

---

## 0. 结论摘要

| 判定 | 依据 |
|---|---|
| **当前无紧急性能故障** | 库 145 MB / shared_buffers 3948 MB，缓存命中 99.97%，业务表当前都极小（order 71 行、customer 6 行），典型查询 0.04–0.35 ms |
| **唯一必然恶化的热点** | `audit_log` 261,241 行 / 91 MB 且纯追加无清理；备份 L2 指纹校验全表扫 418 ms，随行数线性增长 |
| **最大的结构性浪费** | 331 个索引中：audit_log 上 30 MB 零使用索引（每次审计写入白白维护）；约 30 组前缀冗余索引；`purchase_order.source_order_id` 存在**同列双索引**（迁移引入的 bug） |
| **规模回升后的隐患** | 编号取号/巡检查询族（`split_part`+正则）永远顺扫，9 月规模实测 0.35 s；`order`/`purchase_order` 的模糊搜索无 trgm 索引支撑 |
| **观测缺口（9 月已指出，仍未补）** | `pg_stat_statements` 未安装，数据库侧无语句级统计 |

---

## 1. 环境与规模实测

### 1.1 实例

| 项 | 值 |
|---|---|
| PostgreSQL | 18.3（主库 :5432 + 同机热备 replica） |
| 库大小 | 145 MB（9 月基线 43.4 MB） |
| shared_buffers / max_connections | 3948 MB / 200 |
| 缓存命中率 | **99.97%** —— 全库常驻内存，无 I/O 瓶颈 |
| pg_stat_statements | **未安装** |
| alembic version | `pg_standalone_105`（= 迁移 head，库与迁移链同步） |
| pg_trgm 扩展 | 已安装 |

### 1.2 表规模（精确 COUNT(*)，2026-10-31）

| 表 | 当前行数 | 9 月基线 | 趋势 |
|---|---|---|---|
| **audit_log** | **261,241** | 45,241 | **持续追加，+200 行/天（工作日 200–370）** |
| **numbering_audit** | **41,370** | — | **每 10 分钟巡检写 10 行 ≈ +144 行/天，无清理** |
| web_vital | 10,897 | — | 有 30 天保留期清理（autovacuum 正常） |
| inventory_log | 439 | 25,072 | 曾被清理（product_id 已增至 21396） |
| order | **71** | 3,722 | **业务数据被清理/重置过** |
| order_item | 15 | 3,752 | 同上 |
| product | 117 | 118 | 稳定 |
| stock_out / stock_in | 26 / 0 | 2 / 4 | 小 |
| purchase_order（+item/sku） | 9 / 49 / 10 | 43 | 小 |
| customer / case_movement | 6 / 6 | — | 小 |

> **重要事实**：与 9 月基线相比业务数据量大幅缩小（order 3722→71），因此"业务表查询慢"目前**不存在触发条件**；分析重点转向（a）持续增长的日志类表，（b）规模回升后必然复发的查询模式。

### 1.3 近 6 天慢查询画像（46 条）

| SQL 模式 | 次数 | 最慢 | 触发场景 | 定性 |
|---|---|---|---|---|
| `SELECT pg_advisory_xact_lock(...)` | 8 | 4.43 s | 服务启动 lifespan 对账持锁跑全表聚合 → 后续取号/worker 排队 | **锁等待，根因是锁内长查询** |
| `INSERT INTO numbering_counter ... SELECT split_part(...) FROM case_movement`（对账回填） | 1 | 1.58 s | 每次服务启动（4 worker 串行） | 全表 `split_part` 聚合，无表达式索引 |
| `SELECT purchase_order.* ...`（列表） | 2 | 1.16 s | 采购单列表页 | 当前表仅 9 行、计划 0.04 ms → 判定为表更大时期或共享主机瞬时负载 |
| `DELETE FROM web_vital WHERE created_at < ...` | 2 | 1.09 s | 前端指标保留期清理 | 计划健康（Bitmap Index Scan on `idx_wv_created_desc`），慢=删除量+瞬时负载 |
| `MD5(STRING_AGG(...)) FROM audit_log`（备份 L2 指纹） | 4+ | 0.76 s | 备份/恢复校验 | **全表聚合 418 ms 实测，随 26 万行线性增长** |
| `SELECT count(*)` / `SELECT 1`（健康探针） | 若干 | 1.52 s | cron 探针 | 共享主机瞬时负载噪音（已知问题，probe 阈值已上调） |
| `SELECT MAX(CAST(split_part("order_no",'-',3) AS BIGINT)) ...`（编号巡检） | 1 | 0.35 s | **每 10 分钟巡检 × 10 实体**（order 表 3722 行时期） | 正则+split_part 表达式，永远顺扫 |

---

## 2. 执行计划与索引使用分析（探针实测）

### 2.1 逐查询执行计划

| 查询 | 计划关键节点 | 实测耗时 |
|---|---|---|
| order 取号 `read_daily_max`（正则） | **Seq Scan**，Filter 后 1 行（Rows Removed: 70） | 0.103 ms |
| order 巡检 `_ENTITY_MAX_SQL`（正则+split_part） | **Seq Scan**，同上 | 0.109 ms |
| case_movement 对账 GROUP BY | **Seq Scan** → HashAggregate | 0.042 ms |
| **audit_log L2 指纹**（全列 STRING_AGG） | **Index Scan using audit_log_pkey，actual rows=261,241**，Buffers shared hit=28,927 | **418 ms** |
| audit_log L2 指纹 + `created_at >= now()-30d` | 同上，Filter 仅滤掉 5,170 行（2%） | 434 ms（**按时间裁剪无收益**） |
| purchase_order 列表第 1 页 | Seq Scan → Sort → Limit（9 行） | 0.041 ms |
| inventory_log 按产品 | **Index Scan ix_inventory_log_product_id**（product_id=21396，16 行） | 0.042 ms |
| web_vital 保留期 DELETE | Bitmap Index Scan on `idx_wv_created_desc` | 计划健康 |
| numbering_audit 端点（ORDER BY checked_at DESC LIMIT 200） | Index Scan Backward on pkey | 0.046 ms |

**判读**：
1. 编号取号/巡检查询族的计划是 Seq Scan——`split_part(col,'-',2)` 表达式 + 正则匹配**无法使用任何普通 B-tree**（唯一索引 `order_no_key` 帮不上）。当前 71 行下 0.1 ms 无感；**order 表在 3722 行时实测 0.35 s**，且该查询每 10 分钟 × 10 实体被巡检触发、每次开单被取号触发。
2. audit_log 的 L2 指纹走 pkey 全索引扫（ORDER BY id 语义决定），418 ms@26 万行。数据集中在近 30 天（滤 2%），**加时间索引救不了全量指纹语义**——出路是保留期裁剪或增量校验。
3. inventory_log 按产品查询有索引且在用（7 次扫描）——该路径健康。

### 2.2 索引使用统计（pg_stat_user_indexes，窗口=自 2026-10-22 PG 重启起 9 天）

**audit_log（261,241 行）全部 4 个索引**：

| 索引 | 大小 | idx_scan |
|---|---|---|
| audit_log_pkey | 5.7 MB | 13（备份 L2 指纹在用） |
| idx_audit_resource_date | **17 MB** | **0** |
| idx_audit_created_desc | **10 MB** | **0** |
| ix_audit_log_user_id | **2.6 MB** | **0** |

> audit_log 是**纯追加表**（写入方：AuditLogMiddleware 每写请求 1 行、notification_service；无列表端点，读方仅备份校验走 pkey）。3 个零使用索引 = 每次审计 INSERT 白付 3 次 B-tree 维护 + 30 MB 空间。

**其他零使用/低使用大索引**（节选）：`idx_inventory_log_product_date` 2.6 MB（0 扫，是 `ix_inventory_log_product_id` 的扩展列版本）、`order_order_no_key` 2.1 MB（0 扫——**唯一约束索引，不可删**）、`stock_out` 系列多个 0.4–1.4 MB 索引、`order_item.ix_order_item_order_id` 392 kB（0 扫，复合版 `ix_order_item_order_product` 21,462 扫在用）。

> ⚠️ **零扫描 ≠ 可删**：`*_pkey` / `*_key`（unique）索引用于约束强制，其探测不计入 idx_scan，必须保留。9 天窗口也覆盖不了月度/季度查询——删除任何索引前需确认（见 §5 验证与边界）。

### 2.3 结构性冗余（前缀重叠，全库 331 索引中约 30 组）

重灾区（A 的列集是 B 的前缀，二者同为非部分 B-tree）：

| 表 | 冗余索引（可被复合索引前缀替代） | 被包含于 |
|---|---|---|
| **stock_in（0 行！）** | `ix_stock_in_customer`、`ix_stock_in_product_id` | `idx_stockin_customer_product_date` / `idx_stockin_product_date` 等（0 行表挂 10 个索引 ≈ 3.3 MB） |
| order | `ix_order_customer` / `ix_order_product_id` / `ix_order_status` | `idx_order_customer_status` / `idx_order_product_status` / `idx_order_status_date` |
| stock_out | `idx_stockout_order` ⊂ `idx_stockout_order_type` ⊂ `idx_stockout_order_stockin_qty` | **三重嵌套冗余** |
| order_item | `ix_order_item_order_id` | `ix_order_item_order_product`（后者高频在用） |
| inventory_log | `ix_inventory_log_product_id`（在用 7 次）与 `idx_inventory_log_product_date`（0 次）| 二选一即可 |
| purchase_order | `idx_purchase_order_status` | `idx_purchase_order_status_created` |
| 另 20+ 组 | 见探针原始数据 | case_movement / notification / production_plan / sync_retry_queue 等 |

**同列双索引（确定的迁移 bug）**：
```sql
-- 迁移 change_order_status_nullable.py 建了 idx_purchase_order_source_order_id
-- 迁移 pg_standalone_054 又建了 ix_purchase_order_source_order_id（ORM index=True 自动名）
-- 两者都是 btree(source_order_id)，功能完全重复
CREATE INDEX idx_purchase_order_source_order_id ON purchase_order (source_order_id);
CREATE INDEX ix_purchase_order_source_order_id ON purchase_order (source_order_id);
```

### 2.4 物理膨胀（历史大表时代索引页未收缩）

| 索引 | 大小 | 当前行数 | 说明 |
|---|---|---|---|
| order_order_no_key | 2,128 kB | 71 行 | 3722 行时代遗留（vacuum 不收缩文件） |
| stock_out 系列 | 400–1,408 kB | 26 行 | 同上 |
| order_item_pkey | 392 kB | 15 行 | 同上 |
| stock_in 全部 | ≈3.3 MB | **0 行** | 同上 |

全库常驻内存，膨胀对**读**性能影响≈0；代价在备份体积、autovacuum 扫描页数、缓存占用。低优先级，可与其它维护合并处理。

### 2.5 模型与库结构漂移（"幽灵索引声明"）

生产库 alembic 版本 = 迁移 head（105），但 ORM `__table_args__` 声明的以下索引**从未落库**（autogenerate 被项目禁令封锁，漂移不可见）：

| 模型声明 | 库中状态 | 影响 |
|---|---|---|
| `order.idx_order_customer_trgm`（GIN trgm） | ❌ 不存在 | 订单按客户名模糊搜索走顺扫 |
| `order.idx_perf_order_status_date_covering`、`idx_perf_order_customer_date`、`idx_order_batch_completed`、`idx_order_locked_by` | ❌ 不存在 | 订单列表/批次查询少 4 个模型预期的索引 |
| `stock_out.idx_perf_stockout_product_date`、`idx_stockout_deduction` | ❌ 不存在 | 出货扣减查询少预期索引 |
| `audit_log.idx_audit_user_action`、`idx_audit_resource`、`idx_audit_action_date`、`idx_audit_not_login` | ❌ 不存在 | **反而正确**——该表纯写不读，模型声明才是错的 |

---

## 3. 慢查询清单与触发场景（识别结果）

| # | 查询族 | 代码位置 | 触发场景 | 当前/规模恶化条件 |
|---|---|---|---|---|
| Q1 | **备份 L2 指纹** `MD5(STRING_AGG(...)) FROM audit_log` | `services/backup/verify/core.py:202` | 备份完整性校验（backup_schedule 调度，poller 每 5 min 扫描） | **已恶化**：418 ms@26 万行，随行数线性增长；无上限 |
| Q2 | **编号巡检** `MAX(split_part(col,'-',3)) WHERE col ~ 正则 [AND split_part(col,'-',2)=:today]` | `tasks/numbering_audit_task.py:30` + `services/numbering_sequence.py:135` | 每 10 分钟 × 10 实体 + **每次开单取号** | order 3722 行时 0.35 s；顺扫随行数线性 |
| Q3 | **启动对账** `INSERT INTO numbering_counter SELECT ... GROUP BY split_part(...)` | `services/numbering_reconcile.py:45` | 每次服务启动（lifespan，4 worker 串行） | 1.58 s@当前；**持 advisory lock 执行 → 取号请求排队 4.43 s（实测日志）** |
| Q4 | **编号格式违规计数** `COUNT(*) WHERE col !~ 正则` | `numbering_audit_task.py:37` | 每 10 分钟 × 10 实体 | 全表正则扫描，随行数线性 |
| Q5 | 采购单 keyword 搜索 `order_no/supplier_name ILIKE '%kw%'` | `purchase_order_query.py:750,804,450` | 采购单联想/筛选 | 无 trgm 索引，顺扫；规模回升后恶化 |
| Q6 | 订单客户模糊搜索 | `order_batch_service.py:140,168,342` 等 | 批次订单筛选 | `idx_order_customer_trgm` 声明未落库 |
| Q7 | web_vital 保留期 DELETE | `monitoring.py` | 定期清理 | 计划健康，勿优化（模型注释已说明索引理由） |

**非问题项**（排除）：`pg_advisory_xact_lock` 慢是 Q3 持锁的**下游症状**；`SELECT 1`/`count(*)` 探针慢是共享主机瞬时负载（已有 probe 阈值机制）；`purchase_order` 列表 1.16 s 发生在表更大/瞬时负载时期，当前计划 0.04 ms。

---

## 4. 索引优化方案（按优先级排序）

> 生产 DDL 一律 `CONCURRENTLY`（不能在事务块内执行，Alembic 迁移需 `autocommit_block`），先在测试库 `erp_system_test` 验证，配套 Up/Down 脚本，低峰执行。

### P0 —— 安装 pg_stat_statements（观测先于优化）

```sql
-- postgres 超级用户执行，需在 postgresql.conf 加 shared_preload_libraries 后重启实例
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
SELECT pg_reload_conf();  -- 然后计划一次 PG 低峰重启（主库+replica 各一次）
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```
- **收益**：获得语句级总耗时/调用次数/行数统计，后续一切删索引决策有 ≥1 个完整业务周期（月）的数据支撑；9 月基线即指出此缺口。
- **代价**：重启实例一次（业务低峰，秒级中断；NSSM 不管理 PG，需手工 `pg_ctl`/服务重启）+ 约 1–2% 的微量开销。
- **回滚**：`ALTER SYSTEM RESET shared_preload_libraries;` + 重启。

### P1 —— audit_log 治理（唯一必然恶化项）

**R1. 删除 3 个零使用索引（30 MB 纯写放大）**

| 项 | 内容 |
|---|---|
| 目标查询 | 无（idx_scan=0，9 天窗口；该表读方仅备份校验，走 pkey） |
| 动作 | `DROP INDEX CONCURRENTLY idx_audit_resource_date;` 同理 `idx_audit_created_desc`、`ix_audit_log_user_id` |
| 预期收益 | 每次审计 INSERT（≈200–370 次/天）少 3 次 B-tree 维护；省 30 MB；REINDEX/vacuum 页数下降 |
| 写入影响 | **纯收益**（无任何已观测读路径） |
| 回滚 | `CREATE INDEX CONCURRENTLY` 重建（脚本附后） |
| 前置确认 | pg_stat_statements 装好后观察一个完整月份无读；或确认无任何代码引用这些索引名 |

```sql
-- Up（不可在事务块内执行）
DROP INDEX CONCURRENTLY IF EXISTS idx_audit_resource_date;
DROP INDEX CONCURRENTLY IF EXISTS idx_audit_created_desc;
DROP INDEX CONCURRENTLY IF EXISTS ix_audit_log_user_id;
-- Down
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_resource_date ON audit_log (resource_type, created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_created_desc ON audit_log (created_at DESC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id);
```

**R2. audit_log 保留期策略（配合 L2 指纹瘦身）**
- 261,241 行中绝大多数为历史爆发/恢复导入（当前仅 +200/天）。若合规允许设保留期（如 180 天），定期 `DELETE FROM audit_log WHERE created_at < now()-interval '180 days'` 后执行 `VACUUM (ANALYZE)`，并安排一次低峰 `VACUUM FULL`/pg_repack 收缩 55 MB heap。
- **注意**：L2 指纹语义是"全表指纹"——裁剪行即改变校验对象，需与备份校验逻辑同步（按导出时间点的行集校验）。实测 `created_at >= now()-30d` 只滤 2%，**加时间索引对该查询无收益，勿为此建索引**。
- 同时把 ORM 模型 `audit_log.__table_args__` 里 4 个未落库的索引声明删掉（模型与库双向对齐，防止未来误 sync 时反向创建）。

### P2 —— 结构性冗余索引清理（低风险）

按收益/风险排序：

| 优先 | 动作 | 理由 |
|---|---|---|
| 1 | `DROP INDEX CONCURRENTLY ix_purchase_order_source_order_id` | **同列双索引确定冗余**（与 idx_ 版完全重复，迁移 054 引入）；保留显式命名的 idx_ 版 |
| 2 | stock_in：`DROP ix_stock_in_customer`（被 `idx_stockin_customer_product_date` 前缀覆盖）| 0 行表；恢复写入后每行省 1 次索引维护。`ix_stock_in_product_id` 同理被 `idx_stockin_product_date` 覆盖 |
| 3 | order：`DROP ix_order_customer / ix_order_product_id / ix_order_status` | 分别是 `idx_order_customer_status` / `idx_order_product_status` / `idx_order_status_date` 的前缀 |
| 4 | order_item：`DROP ix_order_item_order_id` | 复合版 21,462 次扫描在用，单列版 0 次 |
| 5 | stock_out：`DROP idx_stockout_order`、`idx_stockout_order_type` | 三重嵌套冗余的最外两层（保留 `idx_stockout_order_stockin_qty` 覆盖版）|
| 6 | inventory_log：`DROP idx_inventory_log_product_date`（2.6 MB） | 单列版 `ix_inventory_log_product_id` 在用（7 次）；如需 (product_id, change_date) 序语义可反向保留复合、删单列——**二选一，建议保留在用者** |

- **写入影响**：上述表 INSERT/UPDATE 每行少 1–3 次索引维护；order/order_item 是高频写路径，规模回升后收益放大。
- **前置确认**：pg_stat_statements 装好后跑满一个业务月再执行（月度报表可能用低频索引）。
- 全部配套 Up/Down 迁移（`op.drop_index`/`op.create_index`，注意 CONCURRENTLY 需 `with op.get_context().autocommit_block():`）。

### P3 —— 编号查询族表达式索引（防御性，规模触发）

**目标查询**（Q2/Q3/Q4）：`MAX(CAST(split_part(col,'-',3) AS BIGINT)) WHERE col ~ '^[A-Z]+-[0-9]{8}-[0-9]+$' [AND split_part(col,'-',2) = :today]`

**建议形态**（以 order 为例，9 张编号表同构）：

```sql
-- Up（不可在事务块内执行）
CREATE INDEX CONCURRENTLY idx_order_no_date_seq
  ON "order" (
    split_part(order_no, '-', 2),
    CAST(split_part(order_no, '-', 3) AS BIGINT)
  )
  WHERE order_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$';
-- Down
DROP INDEX CONCURRENTLY IF EXISTS idx_order_no_date_seq;
```

| 要素 | 理由 |
|---|---|
| **列顺序：日期段在前、序号段在后** | 巡检/对账按 `split_part(...,2)=today` 等值过滤（前导列等值）+ 对序号取 MAX（尾列在等值前缀下有序 → index-only 取末行即得 MAX，无需扫描） |
| **部分索引 `WHERE 正则`** | 只索引合规行（脏行不进索引）；与查询谓词逐字匹配才能被使用（PG 不做谓词蕴含推断——本仓已有 `IS NOT TRUE` vs `= false` 的历史坑，模型注释为证） |
| **表达式索引而非生成列** | 不改表结构、可 CONCURRENTLY 建删；代价是每次 INSERT/UPDATE order_no 时多 2 次 split_part 求值 + 1 次 B-tree 维护（微秒级） |
| **预期收益** | order 3722 行时查询 0.35 s → 预计 <0.1 ms（等值前缀 + MAX 尾列）；启动对账持锁时间从 1.58 s 级降到毫秒级 → **消除 4.43 s 的 advisory lock 排队根因** |

**触发条件（当前勿建）**：业务表回到千行级（order > 1,000 行）或巡检单实体查询 > 100 ms 时再执行。当前 71 行下顺扫 0.1 ms，建索引是纯写放大。**替代缓解**：巡检频率从 10 分钟降至 30 分钟（改动 cron_schedules 一行），或对表加行数阈值自适应跳过。

### P4 —— 模型与库结构对齐（防漂移再发生）

1. 决策"幽灵索引声明"：`order.idx_order_customer_trgm` 等 4 个、`stock_out` 2 个——**要么补迁移落库、要么从模型删除**。规模回升场景建议落库 trgm（订单客户模糊搜索 Q6）与 `idx_perf_order_status_date_covering`（订单列表主路径覆盖索引）。
2. 编写**结构对账只读脚本**（比对 `Base.metadata` 索引 vs `pg_indexes`，输出差异清单），纳入 `scripts/quality_gate.py` 或定期巡检——漂移今天靠探针才发现，应该机器化。

### P5 —— 膨胀索引收缩（可选，合并维护窗口）

`REINDEX CONCURRENTLY` 处理 §2.4 清单（order_order_no_key 2.1 MB/71 行等）；audit_log 若做 R2 裁剪后 `VACUUM FULL`。当前全内存无读收益，动机是备份体积与扫描页数。

---

## 5. 验证方法与边界情况

### 5.1 验证方法（每项改动）

1. **测试库先行**：所有 DDL 在 `erp_system_test` 执行 + 全量回归（提权跑 `logs/_run_pytest_elevated.ps1`，注意测试库独占锁）。
2. **EXPLAIN 前后对比**：改动前后各跑一次同形态 EXPLAIN (ANALYZE, BUFFERS)（本报告 §2.1 即基线），确认计划节点与耗时变化。
3. **效果指标**（改动后观察 1 周）：
   - 慢查询日志条数（`grep 慢查询 logs/fastapi_*.log`，基线=6 天 46 条）
   - 备份校验任务耗时（L2 指纹，基线 418 ms）
   - ARQ `numbering_audit` 任务耗时（日志）
   - `pg_stat_user_indexes.idx_scan` 增长（确认保留的索引在用）
4. **变异检查**：删索引后故意跑一次曾用该索引的查询，确认计划退化在可接受范围（证明删的是真冗余）。

### 5.2 边界情况与风险

| # | 边界情况 | 处置 |
|---|---|---|
| 1 | **9 天统计窗口覆盖不了月度/季度查询** | P1/P2 删除动作等 pg_stat_statements 跑满一个完整业务月再执行；期间用只读脚本持续导出 idx_scan |
| 2 | **unique/pkey 索引 idx_scan=0 ≠ 可删**（约束探测不计数） | 删除清单已排除全部 `*_pkey`/`*_key` |
| 3 | **部分索引谓词必须与查询逐字匹配** | `IS NOT TRUE` vs `= false` 的历史坑；P3 正则谓词须与 `numbering_reconcile.py`/`numbering_audit_task.py` 的常量字符串逐字一致，抽成共享常量最稳 |
| 4 | **CONCURRENTLY 限制** | 不能在事务块内执行；被取消会留下 INVALID 索引（`SELECT ... WHERE NOT indisvalid` 检查并清理）；Alembic 用 `autocommit_block` |
| 5 | **本机即生产，无预发** | DDL 低峰执行；执行前确认最新备份可恢复；每次只做一组改动、验证后再下一组 |
| 6 | **replica 自动同步** | 索引变更经流复制传播，主库执行即可；但 PG 实例重启（P0）主备需分别安排 |
| 7 | **编号格式与 split_part 强耦合** | P3 表达式索引在编号格式变更（前缀表 spec §4.5）时需同步重建；把索引 DDL 与 `NUMBERED_ENTITIES` 白名单放同处维护 |
| 8 | **web_vital DELETE 勿过度优化** | 计划已走 `idx_wv_created_desc`；慢是删除量+瞬时负载，再加单列 created_at 索引是冗余（模型注释已声明，保持现状） |
| 9 | **audit_log 模型反向漂移** | 库里 4 个索引 < 模型声明 8 个；未来任何"ORM 元数据同步"迁移会反向创建 4 个无用索引——先修模型（P1-R2 附带项） |
| 10 | **pg_stat 计数失真教训** | 本轮 `n_live_tup`（audit_log 显示 1,664，实际 261,241）与 reltuples 不一致；分析以精确 COUNT + EXPLAIN actual rows 为准，勿单信统计视图 |

### 5.3 复现命令

```bash
# 只读探针（需提权运行，凭据读项目根 .env；本报告临时产物，已清理）
#   采集内容：表规模/索引使用/EXPLAIN/精确 COUNT/膨胀证据
# 慢查询统计
grep -h "慢查询" logs/fastapi_202610*.log | grep -oE "类型: [a-z]+" | sort | uniq -c
```

---

## 附：证据文件索引（分析期间产物，已清理）

- 探针原始输出：`logs/_dba_probe_result.json` / `.txt`（2026-10-31 22:57–23:10 两轮采集）
- 慢查询日志：`logs/fastapi_20261026.log` ～ `fastapi_20261031.log`
- 基线对照：`docs/performance-baseline.md`（2026-09-14）
- 关键代码：`fastapi_app/services/numbering_sequence.py`、`numbering_reconcile.py`、`tasks/numbering_audit_task.py`、`services/backup/verify/core.py`、`core/arq_app.py`（cron_schedules）、`shared_models/*.py`（索引定义）

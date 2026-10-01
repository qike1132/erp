# 03 · 数据层 / 模型 / 迁移审计（t3 残片合并 + 缺口声明）

> **本文件元信息**（由 docs-archivist 于归档时统一添加，正文未改）
>
- **审计轮次**：2026-10-01 第二轮全面审计（binfa-ERP / D:\erp_system）
- **基线**：aac4c43f59a4374e05cdc5aee6c4aaa8afc99026（2026-10-01 14:52:03，成员取证时的 HEAD）
- **归档 HEAD**：546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43，chore(types): mypy 覆盖 106→110（OPT-13 第一批），顺带删 staging_utils 死代码）
- **来源**：成员报告 `t3-data.report.md（2,071 B 片段）+ t3-data.fallback.md（4,777 B 收尾摘要）`（恢复件 2,071 + 4,777 B / 4,999 字符）
- **恢复方式**：captain 从 t3 成员会话转录恢复到的**残片**合并而成（按「正文片段 → 收尾摘要」顺序拼接，逐字保留，数字未改写）。**不是**从任务 output 恢复的完整报告。
- **完整性**：**不完整（等级：高）** —— t3 完整 output 随团队状态目录被删而永久丢失；缺失项见下方「完整性缺口声明」，必须重跑 t3 才能补齐。
- **只读声明**：全程只读静态审计：不改代码/配置/数据库，不重启服务、不装依赖、不发起任何攻击性请求；临时脚本仅写 %TEMP%\erp_audit_v2\。本文件是审计产物的**归档副本**，正文结论与 文件:行 证据保持成员原文。
- **归档时间**：2026-10-01（第二轮审计当日）

【硬性提醒】所有 文件:行 均相对基线 aac4c43f 取证；归档时仓库 HEAD = 546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43）已在其上新增 1 个提交（mypy 覆盖 106→110、顺带删 staging_utils 死代码），行号可能已漂移，引用前请重新核对。

**归档者独立复核（本轮实测，非成员转述）**：抽查 t3 头号发现（approval 表内时钟混写）：`fastapi_app/shared_models/approval.py:21-22` `_utcnow()` 为 naive UTC、`:56` request_time default=_utcnow、`:61` updated_at default=datetime.now,onupdate=datetime.now、`:128` action_time default=_utcnow、`:130` updated_at 同上 —— 逐字命中，同表 8 小时混写成立。另核 `migrations/versions/pg_standalone_054_sync_schema_with_orm_metadata.py:651` 确有 downgrade()、`:24` docstring 自述只做结构层面回退。**未复核**（属 t3 已声明局限）：库内索引/列/FK 的 DB 侧统计需连库，本轮未连库。

---
## 片段 A · 原始正文残片（来源 t3-data.report.md，2,071 B）

- ORM 索引声明总数 280，DB 非主键索引 256。ORM 索引名在库中不存在 54 个，其中 21 个「同名不存在但同列集存在」= 纯命名漂移（如 audit_log ix_audit_log_created_at ↔ idx_audit_created_desc、staging_* ix_*_session_id ↔ idx_*_session、order idx_perf_order_customer_date ↔ ix_order_customer），**真正缺失 33 个**：approval_log idx_approval_log_actor[actor_id]；audit_log idx_audit_action_date[action,created_at]、idx_audit_not_login[]、idx_audit_resource[resource_type,resource_id]、idx_audit_user_action[user_id,action]、ix_audit_log_action[action]、ix_audit_log_resource_type[resource_type]；customer_access_log idx_customer_access_log_customer[customer_id]、idx_customer_access_log_user[user_id]；material_registration idx_material_reg_order_no[purchase_order_no]、idx_material_reg_purchase_order[purchase_order_id]、idx_material_reg_status_date[status,registration_date]；material_registration_item idx_material_reg_item_order_item[order_item_id]；modification_log idx_modification_log_modifier[modifier_id]；order idx_order_batch_completed[]、idx_order_locked_by[locked_by_id]、idx_perf_order_status_date_covering[status,id]；order_status_log idx_order_status_log_operator[operator_id]；order_sync_config idx_order_sync_config_updated_by[updated_by_id]；permission idx_permission_parent[parent_id]；product idx_perf_product_name_date[id]；product_accessory idx_product_accessory_supplier[supplier_id]；product_fabric idx_product_fabric_supplier[supplier_id]；product_material idx_product_material_product[product_id]、idx_product_material_supplier[supplier_id]；purchase_order idx_po_status_date_covering[status,id]、idx_purchase_order_created_by[created_by]、idx_purchase_order_supplier_status[supplier_id,status]；staging_order idx_staging_order_product[product_id]；staging_stock_in idx_staging_stockin_product[product_id]；staging_stock_out idx_staging_stockout_product[product_id]；stock_out idx_perf_stockout_product_date[product_id]、idx_stockout_deduction[product_id]。

## 片段 B · 收尾摘要（来源 t3-data.fallback.md，4,777 B）

t3「数据层/模型/迁移审计」已完成并提交（attempt `4b0ab279-…`，status=completed），完整 7 问结论 + 逐项证据 + DDL 清单已写入 t3 任务 output，并已用 `agent_teams_send_message` 报给 captain。全程只读：DB 连接后立即 `SET default_transaction_read_only = on`，无 DDL/DML，未改任何文件、未重启服务，结构解析全部用 ast（脚本在 `%TEMP%\erp_audit_v2\`）。

## 七问结论

| # | 结论 | 严重度 |
|---|---|---|
| ① 迁移图 | **严格单 head**：REVISIONS 99 / EDGES 109 / HEADS 1 / LEAF 1 / DANGLING 0 / TOPO_LEN 99 / 无环；head=`pg_standalone_060_fix_updated_at_varchar_columns`，与生产库 `alembic_version` 一致。但**非线性**：4 根 + 6 个 merge 节点，最长链 79 步 | 中 |
| ② 模型↔迁移漂移 | 列方向干净（ORM 754 列 0 缺失）；反方向库多 4 列 + 3 表；索引 ORM 280 vs 库 256，名缺失 54 中 **33 个真缺失**、21 个纯改名 | 中高 |
| ③ FK 索引矩阵 | 单列 FK **86 个，31 个无前导索引**（30 个完全无可用索引）；ORM 口径只报 11 —— 19 个差额正是②的漂移 | 中 |
| ④ N+1/lazy | relationship 81 条、**59 条未声明 lazy**（默认 select）；`passive_deletes` 0 条；业务路径真实 N+1 **34 处** | 中高 |
| ⑤ 连接池/会话 | workers=8 → 单 worker 8 连接 ×8 = 64 直连，逼近 `max_connections=100`；`DB_POOL_SIZE/DB_MAX_OVERFLOW/DB_POOL_RECYCLE` 全是死配置；无 pool_recycle；commit 在响应之后 | 中 |
| ⑥ 审计/时间戳/软删除 | **发现 1 个数据正确性 bug**；20 个 NOT NULL 时间列无 DB 默认值；updated_at 触发器 0；命名双轨；软删除三套语义 | 中高 |
| ⑦ JSON/Text | JSON 仅 4 列（克制）；Text 56 列、4 个 NOT NULL 存结构化数据 | 低 |

## 三条最硬的发现

1. **approval 表内时钟混写（真 bug）**：`fastapi_app/shared_models/approval.py:56`、`:128` 用 `_utcnow()`（naive UTC，`:21-22` 注释明确对应 TIMESTAMP WITHOUT TIME ZONE），但 `approval.py:61`、`:130` 的 `updated_at` 用 `default=datetime.now, onupdate=datetime.now`（**本地时间 UTC+8**）⇒ 同一张表 `request_time` 与 `updated_at` 相差 8 小时，直接影响审批时长统计与审计取证。

2. **schema 真相源三分裂**：`migrations/versions/pg_standalone_054_sync_schema_with_orm_metadata.py` 自称「此后 alembic check 应通过」，实测**不成立**——33 个 ORM 索引在库中既无同名也无同列集索引；库还有 ORM 未声明的 4 列（`customer_sampling_fabric_version.confirmed_at/confirmed_by/status/version_label`）与 3 张库独有表（`alembic_version`、`app_version`、`product_image_orphan_backup`）。任何人跑 `alembic revision --autogenerate` 都会拿到一堆 add_index + 针对那 4 列的 **drop_column 破坏性 DDL**。

3. **迁移链从未端到端重放、回滚整体不可用**：`migrations/versions/merge_resolve_all_heads.py:15-27` 注释记载 merge 父节点曾含 7 个非 head 导致 Alembic `HeadMaintainer._delete_version()` 抛 KeyError、空库 `alembic upgrade head` 无法收尾；另有 4 个 NOOP 迁移、3 处 `downgrade(): pass`、054 的 `downgrade()` 是 `return`。

**③ 的量化补齐**（上一轮唯一未量化项）已逐条给出 31 项「表.列 → 引用 | 现状 | 建议 DDL」，例如 `order.locked_by_id → user.id` 无索引（ORM 声明 `idx_order_locked_by` 但库里没有）、`permission.parent_id → permission.id` 无索引（自引用树查询会全扫）、`purchase_order.(created_by, supplier_id+status)` 无索引；唯一例外是 `product_role.global_role_id` 被 `uq_product_role_product_global(product_id, global_role_id)` 的后置列覆盖，优先级最低。所有建议索引走 `CREATE INDEX CONCURRENTLY`（迁移中用 `migrations/_legacy_base_guard.py:130` 的 `run_concurrently`/`:160` `create_index_if_absent`），风险=生成期写放大、失败留 INVALID 索引。

**可执行清单**已按 P0（时钟修复、20 个时间列 `SET DEFAULT now()`、P0 批 FK 索引）/ P1（061 收口索引+4 列决策、env.py 只读开关、ast 单 head 门禁、池参数接线）/ P2（9 处循环改批量、lazy='raise_on_sql'、死索引清理、命名统一）分级，每条带 文件:行 与风险。

**已声明的局限**：未跑 `alembic check/history`（`migrations/env.py:43-49` 每次命令都会对 `alembic_version` 发 CREATE/ALTER DDL，违反只读约束——这本身也是一条可观测性/工具链发现）；未做空库重放验证；`idx_scan=0` 统计自上次 `pg_stat_reset` 且生产数据量极小（多数表 0–30 行），索引收益只能按结构判断；Pydantic schemas 与 ORM 的字段级一致性本轮未展开。

---

## ⚠️ 完整性缺口声明（归档者添加，必读）

- **t3 的完整原始 output 已丢失**：t3 成员报告原本写入任务 output，随团队状态目录被删除而**不可恢复**。本文件不是完整报告。
- **本文件的构成**：`t3-data.report.md`（2,071 B，仅「ORM 索引声明 vs 库内索引」一个片段的原始正文）+ `t3-data.fallback.md`（4,777 B，成员会话里保留的收尾摘要）。两段合计约 4,999 字符，远小于一份完整七问报告应有的体量。
- **可以确认已包含**：七问结论表（结论 + 严重度）、三条最硬发现、③ FK 索引的量化补齐说明、P0/P1/P2 分级说明、成员自述局限；以及「ORM 280 索引 / 库 256 索引 / **33 个真缺失**」的逐条索引清单。
- **已知缺失（必须重跑 t3 才能补齐）**：① 31 项「表.列 → 引用 | 现状 | 建议 DDL」的**逐条 DDL 清单**（摘要只举例 3 条：order.locked_by_id、permission.parent_id、purchase_order.(created_by, supplier_id+status)）；② ④ N+1 那 34 处的**具体调用点 文件:行**；③ ⑤ 连接池 4 个死配置的**具体配置键位置**；④ ⑥ 20 个 NOT NULL 时间列与软删除三套语义的**逐表清单**；⑤ 七问的完整证据链与全部可复现命令。
- **恢复件旁证**：`t3-data.fallback.md` 首行记载 t3 任务曾以 attempt `4b0ab279-…` 提交 `status=completed` —— 成员侧确认产出过完整报告，丢失发生在产出之后。
- **重跑建议**：只需只读连接（成员原始做法：连库后立即 `SET default_transaction_read_only = on`）；注意 `migrations/env.py:43-49` 每次 alembic 命令都会对 `alembic_version` 发 CREATE/ALTER DDL，会违反只读约束。


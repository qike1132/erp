# Alembic 迁移图说明

> 本文件由 2026-09-30 架构评审的 S10 项补齐。它记录**现状**，不改变任何迁移。
> 约束由 `scripts/check_alembic_heads.py` 自动把关（pre-commit + quality gate）。

## 一句话现状

142 个 revision、**单 head**、**4 个 root**、6 个 merge revision。迁移文件零业务代码
泄漏（`migrations/` 导入 `fastapi_app` 的次数为 0）。

- head：`pg_standalone_102_purchase_order_status_check`（仓库链头；生产库实际版本以
  `alembic current` 为准，本迁移尚未应用到生产）
- root（base）：`add_pp_composite_idx`、`add_product_factory`、`add_product_price`、`pg_standalone_001`

> 数字由 `scripts/check_alembic_heads.py` 的输出维护（revisions=142 heads=1 bases=4）；
> 新增迁移后同步更新本节，避免 README 再次成为过期第二真相源（Z08-R6）。

## 删表迁移的行数守卫缺口（Z08-R3，重建库时人工复核）

以下历史迁移使用 `op.drop_table` 但未调用 `_legacy_base_guard.drop_table_if_empty`；
当前生产已被版本表拦截，重建库/回滚重放前请人工确认旧表数据可弃：

- `9b7b1ead6c4a_add_phone_column_to_user.py`（bom_file / process_file / staging_* 5 表）
- `pg_standalone_017_pattern_room_v2.py`（pattern_room 旧 4 表）
- `pg_standalone_027_drop_pattern_room_tables.py`（8 张遗留表）
- `pg_standalone_062_case_management_rebuild.py`（case_stock_in / case_stock_out / case_inventory_log）

## 大表回填模板（Z08-R2，后续迁移必读）

`pg_standalone_058` / `073` 的全表 UPDATE 在 alembic 单事务内持锁到提交；两者已应用，
不必返工，但**新迁移不要复制该模式**。大表回填必须：

1. 按主键游标分批（`WHERE id > :last ORDER BY id LIMIT N`），每批独立提交
   （`run_concurrently` / autocommit block），避免长时间行锁与 WAL 膨胀；
2. 若无法分批，迁移 docstring 必须显式标注「须在停机窗口执行」及预计耗时；
3. 回填前后各跑一次 `COUNT(*)` 复核，差异写日志。

## po_dedup 唯一索引链（Z08-R4，结构性风险提示）

`uq_po_pending_dedup` 在链上被三个迁移重建过（`add_po_dedup_unique_index` →
`rebuild_po_dedup_index`（supplier_id 版）→ `rebuild_po_dedup_use_supplier_name`
（supplier_name 版，经 019 merge 汇合）。当前空库 `upgrade head` + `alembic check`
验证终态与 ORM（supplier_name 版）一致；但终态依赖拓扑执行序，新增/调整分支时
必须重新跑空库校验，禁止再新增同名 DROP+CREATE 迁移。

## product_name 快照双实现（Z08-R5，维护约定）

`pg_standalone_087` 的 BEFORE INSERT 触发器是 product_name 快照的**权威口径**；
`product_service.delete_product` 的 coalesce 回填只用于兜底存量行。修改任一处必须
同步评估另一处，并在 PR 描述中说明两处口径是否仍然一致。

## 为什么会有 4 个 root

仓库早期有多条并行开发线（物料/产品域、采购域、PostgreSQL 独立部署线），
各自从空库起链，后期用 merge revision 收敛。这是历史事实，**不要为了"好看"重排**：
重排会改写已应用到生产库的 revision 序列。

## 收敛路径（base → 第一次汇合）

```
add_product_price   → add_product_version → add_supplier_purchase_order → add_production_plan
                    → add_customer_to_purchase_order → add_customer_code_to_customer
                    → add_batch_no_to_order → [fork: 9b7b1ead6c4a | add_order_type_country_stockin]

add_product_factory → pg_standalone_019_customer_sampling (merge) → pg_standalone_020..025
                    → [fork: add_outsource_module | pg_standalone_026_search_trgm]

add_pp_composite_idx ┐
pg_standalone_001    ┴→ … → merge_all_heads (merge, 7 父) → merge_resolve_all_heads (merge, 4 父)
                        → [fork: add_file_records_table | add_po_dedup_unique_index]
```

## 6 个 merge revision（父子关系）

| merge revision | 合并的父 revision |
|---|---|
| `merge_all_heads` | pg_standalone_003, add_order_batch_fields, add_order_type_country_stockin, add_pp_composite_idx, add_stock_return, add_updated_at, a8f3c2d1e5b7 |
| `merge_resolve_all_heads` | merge_all_heads, add_country_table, add_missing_perf_idx, pg_standalone_013 |
| `rebuild_po_dedup_use_supplier_name` | add_file_records_table, add_user_factory_and_notification |
| `pg_standalone_019_customer_sampling` | pg_standalone_017_pattern_room_v2, rebuild_po_dedup_use_supplier_name, add_product_factory |
| `add_outsource_module` | partition_order_by_year, pg_standalone_025_add_cs_indexes |
| `add_order_confirm_fields` | add_outsource_module, pg_standalone_027_drop_pattern_room |

## 新增迁移时的规则

1. **必须 `down_revision = '<当前 head>'`**，不要复制旧模板里的历史 revision id。
2. 需要并行开发时，各自以 head 为父，合流时用
   `alembic merge -m "merge <分支说明>" <rev1> <rev2>`。
3. 提交前跑 `python scripts/check_alembic_heads.py`：head 必须恰好 1 个，
   root 数不得超过 4（要新增 root 得改脚本里的 `EXPECTED_MAX_BASES` 常量并说明理由）。
4. **不要用朴素 AST 统计迁移图**。只认 `ast.Assign` 会漏掉 `AnnAssign`
   （`revision: str = ...`），实测会得出「5 roots / 4 heads / dangling
   pg_standalone_003,007」的伪影。要用 `alembic.script.ScriptDirectory`。

## 常用命令

```bash
# 在仓库根目录执行（alembic.ini 已补齐；sqlalchemy.url 由 migrations/env.py 覆盖）
alembic heads          # 查看 head（应为 1 个）
alembic current        # 查看当前库已应用到哪个 revision
alembic history -r-5:  # 最近 5 条
alembic upgrade head   # 升级
```

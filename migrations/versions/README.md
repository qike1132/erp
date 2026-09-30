# Alembic 迁移图说明

> 本文件由 2026-09-30 架构评审的 S10 项补齐。它记录**现状**，不改变任何迁移。
> 约束由 `scripts/check_alembic_heads.py` 自动把关（pre-commit + quality gate）。

## 一句话现状

99 个 revision、**单 head**、**4 个 root**、6 个 merge revision。迁移文件零业务代码
泄漏（`migrations/` 导入 `fastapi_app` 的次数为 0）。

- head：`pg_standalone_060_fix_updated_at_varchar_columns`（与生产库 `alembic current` 一致）
- root（base）：`add_pp_composite_idx`、`add_product_factory`、`add_product_price`、`pg_standalone_001`

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

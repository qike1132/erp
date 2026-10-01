# ADR：迁移链 4 个根为历史外观问题，不做修改

- 状态：已接受（2026-10-01）
- 背景：`docs/architecture-review-2026-10-01.md` §2.8 与 `docs/optimization-plan-audit-2026-10-01.md` BLOCKER B1
- 影响范围：`migrations/versions/`（99 个迁移）

## 决策

**不对迁移链做任何"修根"操作**（不 merge、不 squash、不改文件名、不改 down_revision）。

## 依据（AST 实证，2026-10-01）

1. 99 个迁移**单 head**：`pg_standalone_060_fix_updated_at_varchar_columns`，无悬空引用。
2. 4 个根（`pg_standalone_001`、`add_product_factory`、`add_product_price`、`add_purchase_plan_composite_indexes`）**全部收敛到唯一 head**——从 head 沿 down_revision 反向可达 99/99 个文件，图是连通的。
3. 因此 `alembic merge` 无对象（merge 只能合并并行的多个 head）；全新环境 `alembic upgrade head` 与既有环境均不受 4 根影响——**它只是外观问题，不是功能缺陷**。
4. 同号 017 有 3 个文件（`pg_standalone_017_add_po_source_order_ids_gin_index` / `_pattern_room_v2` / `_product_aggregate_mv`），因文件名已进入各环境 `alembic_version` 表与历史脚本，改名会破坏已部署环境。

## 后果

- 新增迁移一律以当前 head（060 系）为 down_revision，保持单 head。
- 若未来确需线性化，唯一安全路径是「导出全量数据 → 重建基线迁移 → 全新环境验证 → 数据回灌」，属于大工程且当前零收益，明确不做。
- 本 ADR 的存在即是把"为什么不动它"固化，防止后人误判为待修债务。

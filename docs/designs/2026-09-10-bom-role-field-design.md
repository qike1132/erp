---
design_type: feature
created_at: 2026-09-10
---

# BOM 配置·角色字段（SKU 与角色一对多 + 每角色独立 BOM）

> 状态：设计已获用户确认（HTML 效果图 v5）
> 日期：2026-09-10
> 效果图：`docs/ui-redesign/bom-role-效果图.html`

## Intent Contract

```yaml
intent: 为 BOM 表配置增加"角色"支持——一个 SKU 可关联不定数量的角色，每个角色拥有独立的面料/填充/辅料物料清单；点击角色标签自动切换到该角色 BOM；无角色产品保留产品级默认 BOM
constraints:
  - 不改变 has_bom / 物料聚合 / 采购计算语义（角色 BOM 只是同一批物料表中按 role_id 归属的更多行）
  - 不修改 Product.to_dict()（避免 lazy="raise" 触发）；产品列表不展示角色
  - 现有无角色产品的 product_material 唯一约束需改为 (product_id, role_id) 复合唯一，存量行 role_id 为 NULL 不变
  - 删除角色必须弹确认框防误删（前端），并级联删除其物料
success_criteria:
  - 角色可新增/重命名/删除（删除需确认），名称必填、空名禁止保存
  - 点击角色标签切换其独立物料清单，增改删物料归属当前角色
  - get_bom 返回 roles + 带 role_id 的 materials；save_bom 一次提交 roles 与各角色物料
  - 复制 BOM 时角色与其物料一并复制；预览展示角色及物料数
  - 后端单测通过；前端 build:atomic 构建成功
risk_level: low
```

## Verification Contract

```yaml
verify_steps:
  - run tests: python -m pytest fastapi_app/tests/test_bom_role.py -v
  - check: alembic upgrade head 后 product_role 表存在；product_fabric/product_accessory/product_material 均有 role_id 列；product_material 唯一约束变为 (product_id, role_id)
  - check: get_bom 返回 roles 与各物料 role_id；无角色产品 roles=[] 且物料 role_id=NULL
  - confirm: 前端 npm run build:atomic 成功；BOM 弹窗中角色增删改/切换、删除确认框、物料按角色保存均可用
```

## Governance Contract

```yaml
approval_gates:
  - 设计文档评审（本次）
  - 实施完成后 code-review（hotl:code-review）
rollback:
  - 迁移为新增表 + 加可空列 + 改唯一约束（可安全回滚：删表、删列、恢复唯一约束）
  - 代码改动可 git revert
ownership: 实施者
```

## Scope

| 内 | 外 |
|---|---|
| 新增 `product_role` 表 | 产品列表展示角色 |
| 三张物料表（fabric/accessory/material）增加可空 `role_id` | 修改 has_bom / 物料聚合 / 采购计算 |
| BOM 弹窗：角色标签栏（点击切换、重命名、删除确认、添加） | 修改 Product.to_dict() |
| get_bom / save_bom / copy_bom / preview_bom 支持角色 | 移动端 / 其他入口 |
| BOM 保存一次提交角色与各角色物料 | 角色排序 / 去重约束 |

## Decisions

| # | 决策 | 选择 | 备选（已否决） |
|---|------|------|----------------|
| D1 | 角色与物料关系 | 每角色独立物料清单（物料表加 role_id，NULL=产品级默认 BOM） | 物料共用一套、角色仅分组（与"切换到对应角色 BOM"矛盾） |
| D2 | 无角色产品 | 保留产品级默认 BOM（role_id 为 NULL 的存量行不变） | 强制所有产品必须配角色（破坏存量数据） |
| D3 | 角色入口 | 物料表格正上方常驻角色标签栏，点击切换 BOM；无切换按钮 | 页签区右侧按钮（v2，被否）；表格上方切换替换表格（v3，被否） |
| D4 | 角色删除 | 前端确认框 + 后端级联删除物料（FK ondelete=CASCADE） | 直接删除（用户明确要求防误删） |
| D5 | 填充物唯一约束 | (product_id, role_id) 复合唯一，允许 NULL 多行（PG 语义） | 保持 product_id 唯一（无法支持每角色一条填充） |
| D6 | has_bom | 语义不变：任一物料存在即视为有 BOM（含各角色物料，因同表存储自动覆盖） | 单独判定角色 |

## Surface

**存储**：新表 `product_role(id, product_id FK→product ON DELETE CASCADE, role_name, create_time, update_time)`，索引 product_id。`product_fabric` / `product_accessory` / `product_material` 各加可空 `role_id`（FK→product_role ON DELETE CASCADE，索引）。`product_material` 的 product_id 唯一约束改为 `(product_id, role_id)` 复合唯一。ORM：`Product.roles` 关系（cascade all, delete-orphan, lazy="raise"）。

**API**：`BomSaveRequest` 增加 `roles: list[dict]`；物料项字典透传 `role_id`（int|None）。`GET /product/{id}/bom` 的 product 对象携带 `roles`，materials 各条携带 `role_id`。`POST /product/{id}/bom` 一次提交：角色增删改 + 各角色（及默认）物料增删改。`POST /products/{target}/copy-bom` 复制角色及其物料。`GET /products/{source}/bom-preview` 返回角色列表与各角色物料数。

**组件**：`bom_service`（get/save/copy/preview/search）扩展角色逻辑；`shared_models/product_material.py` 新增 `ProductRole` 模型并给三模型加 `role_id`；`shared_models/product.py` 加 `roles` 关系；`schemas/purchase_center.py` 扩展 `BomSaveRequest`。

**前端**：`BomEditor.vue` 表格上方新增角色标签栏（点击切换、双击重命名、✕ 删除弹确认、＋添加角色内联输入）；`useProductListActions.ts` 增加角色状态与按角色分组的物料状态；`bomTypes.ts` 增加 `Role` 类型、`BomItem.role_id`。

**测试**：新增 `test_bom_role.py` 覆盖：角色增改删（含重命名）、删除级联清理物料、按角色保存/加载物料、默认 BOM（无角色）不受影响、填充物每角色一条、复制 BOM 带角色、空角色名校验。

## Risks & Open Questions

- R1：`product_material` 唯一约束名称与存量数据——迁移需先确认约束名（PG 自动命名 `product_material_product_id_key`），升级前核对生产库。
- R2：删除角色级联删物料为 DB 层行为，前端删除确认文案需明示"将一并删除该角色全部物料"。
- R3：有角色的产品其默认（role_id=NULL）BOM 是否仍可编辑——设计为：一旦存在角色，UI 只展示角色 BOM；存量 NULL 物料在首次保存时归入默认 BOM 或提示迁移。实施时以"保留可编辑性"为底线，避免数据不可达。
- Q1：角色重命名交互采用"双击角色标签进入内联编辑"，待实施前与用户确认（不影响数据模型）。

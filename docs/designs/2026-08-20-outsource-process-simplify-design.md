---
design_type: feature
created_at: 2026-08-20
---

# 订单外发工序弹窗精简重构

## Intent Contract

```
intent: 将订单外发工序弹窗精简为「工序 + 发货数量 + 收货数量 + 操作按钮」的紧凑分组表格，移除时间字段编辑
constraints: 不改后端 API；不改发货/收货/删除/生成工序逻辑与权限判定（canManage/canShip/canReceive）；沿用现有 UiButton/UiDialog 与 oso-* 样式
success_criteria: 弹窗仅 5 列且无任何时间字段；发货为行内输入；type-check 与既有测试通过
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests: cd frontend-vite && npm run type-check
  - run tests: cd frontend-vite && npx vitest run
  - check: 打开 /outsource → 订单 → 弹窗仅 5 列、无时间输入框
  - confirm: 发货/确认收货/删除按状态与权限正确显隐；发货数量回显
```

## Governance Contract

```
approval_gates: [本设计评审]
rollback: git revert（纯前端，无迁移）
ownership: 前端负责人
```

## Scope

| In | Out |
| --- | --- |
| 工序列表由横向流程卡片改为按 SKU 分组的紧凑表格 | 保留横向流程卡片或任何时间字段展示 |
| 移除计划/实际时间展示与 datetime-local 编辑输入 | 修改后端 API 或发货/收货/删除/生成业务逻辑 |
| 精简弹窗头部为 单号/客户/进度 + 状态标签 | 改动权限判定与「贝乐」特殊逻辑 |
| 清理本弹窗独用的废弃逻辑（时间相关） | 影响 /outsource 列表、看板、预设页等其他模块 |

## Decisions

| # | Decision | Choice | Alternatives | Rejected |
| --- | --- | --- | --- | --- |
| 1 | 列表形式 | 按 SKU 分组的紧凑表格（表头行 + 5 列行） | 保留横向流程卡片 | 信息杂、密度低 |
| 2 | 时间字段 | 完全移除展示与编辑 | 只读展示实际时间 | 用户明确「只需数量」 |
| 3 | 弹窗头部 | 精简为 单号/客户/进度；移除「按SKU预设生成工序」按钮与提示（返单自动带出工序） | 保留生成按钮 | 用户后续确认移除 |
| 4 | 状态标签 | 保留（待发货/已发货/已收货徽章） | 移除仅靠按钮区分 | 用户明确保留 |
| 5 | 发货数量输入 | 待发货&可发货时行内 number 输入，其余回显 | 弹窗录入 | 紧凑表格场景内联最简 |
| 6 | 废弃逻辑 | 移除 updatePlanned/toDateTimeLocal/shortDate/detailTotalQuantity | 保留 | 均为本弹窗独用，无孤儿引用 |

## Surface

**组件**：
- `OutsourceProcessFlow.vue`：重写为紧凑分组表格（每 SKU 一组：通栏表头「SKU名 × 数量」+ 工序行），列 = 工序/发货数量/收货数量/状态/操作。发货数量列在 待发货&可发货 时渲染内联输入，否则回显；操作列按状态与权限渲染 发货/确认收货/删除。
- `OutsourceProcessDialog.vue`：头部精简为 单号/客户 + 进度条/百分比/完成数 + 状态标签；移除「按SKU预设生成工序」按钮与提示（返单自动带出工序）；移除「下单日期/数量」meta；收窄传给 flow 的 props（仅 statusLabel + 三个 handler）。

**Composable**：
- `useOutsourceProcess.ts`：删除 `handleGenerate`、`generating`、`updatePlanned`、`toDateTimeLocal`、`shortDate`、`detailTotalQuantity`（均仅本弹窗使用）；保留 `statusLabel`、`progressVariant`、SKU 分组、发货/收货/删除 handler 与权限 computed。

**不动**：`api/outsource.ts` 类型与方法、`outsource.py` 端点、`outsource_service.py`、数据库、/outsource 列表与看板展示。

## Risks & Open Questions

- 多 SKU 订单在表格中的分组视觉（通栏表头行）需与现有 hu/oso 样式一致；实现时复用既有设计变量。
- 行内发货数量输入在数量为空时禁用「发货」按钮，避免无效请求；与现状行为一致。
- 纯前端改动，无数据迁移与后端风险。

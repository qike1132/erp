---
design_type: fix
created_at: 2026-08-18
---

# 湖北订单页新增「全部」TAB 以恢复备货记录展示

## Intent Contract

```
intent: 修复 /beile-order 页面贝乐用户只能看见订单、看不见湖北备货（StockIn）记录的问题：新增「全部」TAB 并设为默认，展示「订单 + 备货」合并列表，保留「未确认 / 已确认」过滤
constraints:
  - 不改后端接口，复用 GET /orders/beile-list 已支持的「不传 confirm_status 即返回订单+备货」能力
  - 保留现有确认流程（未确认 / 已确认 TAB、unconfirmed_count 横幅、确认按钮）不变
  - 仅改动前端：useBeileOrders.ts、HubeiView.vue 及相关测试
success_criteria: 进入 /beile-order 默认「全部」TAB，同时显示湖北订单与备货记录；切到未确认/已确认仍按确认状态过滤订单；备货行无确认按钮、状态列显示 "-"
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run: npm run type-check（frontend-vite）
  - run: npm run test -- BeileOrderTab.confirm.test.ts（frontend-vite）
  - check: 默认 confirmStatus 为 'all'，且 'all' 不向 beile-list 传 confirm_status
  - confirm: 「全部」视图同时渲染订单与备货行；未确认/已确认 TAB 行为与修复前一致
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（本步骤）
rollback: git revert 对 useBeileOrders.ts、HubeiView.vue 与 BeileOrderTab.confirm.test.ts 的改动
ownership: 前端
```

## Root Cause

后端 `order_crud.get_beile_orders_with_stockins` 的 UNION 查询中，备货（StockIn）子查询仅在 `confirm_condition is None` 时参与：

```python
parts = [order_part]
if confirm_condition is None:
    parts.append(stockin_part)
```

而前端 `useBeileOrders.ts` 默认 `confirmStatus = 'unconfirmed'`，且两个 TAB（未确认/已确认）都会把 `confirm_status` 传给后端，导致备货子查询永远被排除，页面上没有任何入口能看到备货记录。

## Scope

| In | Out |
|----|-----|
| useBeileOrders.ts 的 confirmStatus 默认值与查询参数映射 | 后端接口 / 服务层 |
| HubeiView.vue 新增「全部」TAB 按钮 | 其他页面 |
| BeileOrderTab.confirm.test.ts 相关用例 | 移动端 |

## Decisions

| # | 决定 | 说明 |
|---|------|------|
| 1 | 新增「全部」TAB 并设为默认 | 恢复订单+备货合并列表，与后端既有能力对齐 |
| 2 | 用 'all' 表示「全部」状态 | 语义清晰；queryFn 将 'all' 映射为不传 confirm_status |
| 3 | 后端零改动 | `confirm_status` 为空/未传时后端已返回订单+备货 |
| 4 | 未确认/已确认 TAB 保留原逻辑 | 确认流程（unconfirmed_count 横幅、确认按钮、乐观移除）不受影响 |

## Surface

- `frontend-vite/src/views/beile-order/composables/useBeileOrders.ts`：`confirmStatus` 默认值 `'unconfirmed'` → `'all'`；`queryFn` 中 `confirm_status` 改为 `confirmStatus.value === 'all' ? undefined : confirmStatus.value || undefined`。
- `frontend-vite/src/views/hubei/HubeiView.vue`：在确认状态筛选区新增「全部」按钮（置于最前），激活条件 `confirmStatus === 'all'`；computed 兜底值 `'unconfirmed'` → `'all'`。
- `frontend-vite/src/test/BeileOrderTab.confirm.test.ts`：依赖「默认未确认」的用例显式 `setConfirmStatus('unconfirmed')` 后断言；新增「全部」用例验证订单与备货行同时渲染、备货行可见。

## Risks & Open Questions

- 低风险。若「全部」下个别备货仍不显示，则是该备货对应产品 `factory` 字段不是「湖北」的数据问题，需另行排查；订单能正常显示说明同源产品 factory 正确，概率很低。

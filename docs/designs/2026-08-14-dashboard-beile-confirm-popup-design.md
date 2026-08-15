---
design_type: feature
created_at: 2026-08-14
---

# Dashboard 贝乐未确认订单弹窗通知

## Intent Contract

```
intent: 贝乐用户（拥有 beile_order_view 权限）每次登录后首次进入 /dashboard 时，若存在未确认的湖北新订单，弹出通知提示数量，并提供跳转 /beile-order 的入口
constraints:
  - 不改后端接口，复用现有 GET /orders/beile-list 返回的 unconfirmed_count
  - 仅对拥有 beile_order_view 权限的用户弹窗，其余用户不受影响
  - 每次登录会话只弹一次（sessionStorage 标记控制），刷新页面不重复弹
  - 不改变 dashboard 现有数据加载与自动刷新逻辑
success_criteria: 贝乐用户登录后首次进 dashboard、存在未确认订单时弹出通知；确认/取消后本会话不再弹出；非贝乐用户或无非确认订单时不弹
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run: npm run type-check（frontend-vite）
  - check: DashboardView.vue 有 beile_order_view 权限判断、弹窗标记读写正确；useLogin.ts 登录成功清除标记
  - confirm: 贝乐用户登录后首次进 dashboard 且存在未确认订单时弹窗；关闭后刷新不再弹；再次登录重新弹
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（本步骤）
rollback: git revert 对 DashboardView.vue 与 useLogin.ts 的改动
ownership: 前端
```

## Scope

| In | Out |
|----|-----|
| DashboardView.vue 弹窗逻辑 | 后端/接口改动 |
| useLogin.ts 登录后清除弹窗标记 | 其他页面 |
| 复用 UiConfirmDialog 展示数量+跳转按钮 | 移动端 |

## Decisions

| # | 决定 | 说明 |
|---|------|------|
| 1 | 复用 `beile-list` 接口取 `unconfirmed_count` | 无需后端改动，该字段已存在且权限门槛与弹窗对象一致 |
| 2 | 权限判断用 `authStore.hasPermission('beile_order_view')` | 与湖北订单页权限一致，确保只对贝乐用户弹窗 |
| 3 | 弹窗复用 `UiConfirmDialog` | 数量放 text，跳转提示放 sub，确认按钮跳转 `/beile-order` |
| 4 | sessionStorage 标记 `beile_confirm_popup_shown` | 登录成功清除、首次弹窗后写入，实现「每登录会话一次」 |

## Surface

- `frontend-vite/src/views/dashboard/DashboardView.vue`：挂载时若用户有 `beile_order_view` 权限且 sessionStorage 标记未写，调用 `orderApi.beileList({ per_page: 1 })` 读取 `unconfirmed_count`；>0 则打开 `UiConfirmDialog`，确认后 `router.push('/beile-order')`，确认/取消后写入标记。
- `frontend-vite/src/views/login/useLogin.ts`：登录成功后 `sessionStorage.removeItem('beile_confirm_popup_shown')`。

## Risks & Open Questions

- 无高风险；`beile-list` 调用仅发生一次（标记未写时），不影响 dashboard 性能。
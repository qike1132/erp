---
design_type: feature
created_at: 2026-09-20
---

# 外发 TAB 导航：双名标签与顺序调整

## Intent Contract

```
intent: 将外发模块顶部三个 TAB 调整为「收货/发货（同一 TAB 双名）| 外发工序 | 工序预设」，其中第一个 TAB 对贝乐用户显示「收货」、其余用户显示「发货」。
constraints:
  - 不改变路由结构：三个 TAB 仍分别指向 /outsource/shipments、/outsource、/outsource/presets
  - 不改变权限可见性规则：仍由 canOutsource（outsource_manage / outsource_view）控制显隐
  - 不改变各页面内容与页面内已有的「批量发货 / 确认收货」按钮显隐逻辑
  - 判定口径与既有实现一致：用户名 == '贝乐'（与 OutsourceShipmentView.isBeile、后端脚本 BEILE_USERNAME 一致）
success_criteria:
  - 从左到右依次为：收货/发货、外发工序、工序预设
  - 贝乐用户看到「收货」，其余用户看到「发货」（同一 TAB、同一路由）
  - 点击三个 TAB 均正确跳转，激活态跟随路由高亮
  - 既有 OutsourceShipmentView 回归测试全部通过
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests: npx vitest run src/test/OutsourceShipmentView.test.ts
  - check: 新增测试断言——贝乐用户首个 TAB 文本为「收货」，非贝乐用户为「发货」；三个 TAB 顺序为 收货/发货、外发工序、工序预设
  - run: npm run type-check（本文件无新增报错）
  - confirm: 浏览器实测 admin 账号下 TAB 显示「发货」且顺序正确；点击各 TAB 路由与激活态正确
```

## Governance Contract

```
approval_gates:
  - 设计确认后方可实施（本文件）
  - 浏览器实测结果需回报用户
rollback: git checkout -- frontend-vite/src/views/hubei/HubeiRouteTabs.vue frontend-vite/src/test/HubeiRouteTabs.test.ts
ownership: 前端外发模块维护者
```

## Scope

| 范围 | 内容 |
|---|---|
| In | HubeiRouteTabs.vue：调整 TAB 顺序、重命名标签、首 TAB 按身份双名 |
| In | 新增针对标签文本与顺序的回归测试 |
| Out | 路由定义、页面组件内容 |
| Out | 页面内的「批量发货」「确认收货」按钮显隐（已实现且正确） |
| Out | 后端权限与授权脚本 |

## Decisions

| # | 决策 | 选择 | 否决的替代方案 |
|---|---|---|---|
| 1 | TAB 数量 | 3 个（收货/发货、外发工序、工序预设） | 新增独立「工序收货」第 4 个 TAB（后端无对应独立页面可对接） |
| 2 | 首 TAB 命名 | 单一 TAB、按身份显示「收货」或「发货」 | 拆成两个 TAB 分别显示（会出现重复入口） |
| 3 | 身份判定 | 用户名 == '贝乐' | 按权限点 outsource_receive（super 账号同时拥有收发权限，优先级需额外定义） |
| 4 | 顺序 | 收货/发货 → 外发工序 → 工序预设 | 外发工序在最左（与用户明确要求不符） |
| 5 | 标签文案 | 「发货」/「收货」（去掉「单」字） | 保留「发货单」（与用户明确要求不符） |

## Surface

**组件**：`HubeiRouteTabs.vue` 是三个外发页面共用的顶部导航，仅负责渲染 TAB 与路由跳转，不承载业务数据。本次改动集中在其模板的 TAB 顺序与标签文案，以及脚本中新增的身份判定。

**数据**：新增对 authStore 用户名的读取（沿用现有 `useAuthStore` 引入，无需新增依赖）。

**测试**：新增 `HubeiRouteTabs.test.ts`，覆盖标签文案（两种身份）与 TAB 顺序。既有 `OutsourceShipmentView.test.ts` 将 `HubeiRouteTabs` stub 掉，不受影响。

## Risks & Open Questions

- **激活态判定依赖路由前缀**：现有实现用 `route.path.startsWith` 推导激活 TAB，调整顺序不影响该逻辑，但需在实测中确认三个 TAB 的高亮均正确。
- **文案简化的影响**：标签由「发货单」改为「发货」，是用户明确要求；若后续需要区分「发货单列表」与「发货操作」，该文案可能引起歧义。当前页面同时含「批量发货」按钮，实测确认无歧义后即可。
- **待确认**：无。

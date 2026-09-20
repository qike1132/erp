---
design_type: feature
created_at: 2026-09-20
---

# 批量发货弹窗拆分（OutsourceShipDialog 958 行 → 模型 + 双栏子组件）

## Intent Contract

```
intent: 将 958 行的批量发货弹窗拆为「纯函数模型 + 双栏子组件」，主文件及全部新文件 ≤400 行，行为零变化
constraints: 不改任何用户可见行为与 DOM 结构语义；现有 17 个测试不改断言全绿；API 调用不变
success_criteria: check_vue_component_length(400) 对主文件与 3 个新文件全 PASS；quality_gate PASS；三层测试全绿
risk_level: medium
```

## Verification Contract

```
verify_steps:
  - run tests: npx vitest run src/test/OutsourceShipDialog.test.ts src/test/shipCartModel.test.ts src/test/OutsourceShipPickPanel.test.ts src/test/OutsourceShipCartPanel.test.ts
  - check: python scripts/check_vue_component_length.py --max-length 400 与 python scripts/quality_gate.py
  - confirm: 浏览器实测打开弹窗→挑选→编辑数量→底栏计数，与拆分前一致
```

## Governance Contract

```
approval_gates: [设计文档评审, 提交前 diff 复审]
rollback: git revert 单提交（纯前端重构，无迁移）
ownership: 前端负责人
```

## Scope

| In | Out |
| --- | --- |
| 新增 `shipCartModel.ts` 纯函数模型（类型 + 聚合/拆分/校验） | 不改 `GET /processes/shippable`、`POST /processes/ship-multi` 等 API |
| 新增左栏 `OutsourceShipPickPanel.vue`（模板+样式+搜索交互随迁） | 不改任何用户可见 DOM 语义与文案 |
| 新增右栏 `OutsourceShipCartPanel.vue`（模板+样式+单元格编辑随迁） | 不改测试断言（存量 17 个测试保持全绿） |
| 主文件瘦身为壳 + 状态 + 汇总 + 提交 + 底栏 | 不做视觉/交互改动，不新增功能 |
| 新增模型单测 + 两个子组件测试文件 | 不拆分其他巨型组件（CompletedOrdersPanel 等为存量基线） |

## Decisions

| # | Decision | Choice | Alternatives | Rejected |
| --- | --- | --- | --- | --- |
| 1 | 拆分策略 | 纯函数模型 + 双栏子组件 | 仅拆右栏+composable（主文件仍 ~430 超 400）；仅抽 composable（模板+样式 526 行已超标，数学上不可行） | 后两者无法达成 ≤400 硬指标 |
| 2 | 模型层形态 | 独立 `shipCartModel.ts` 纯函数模块 | 逻辑全进 composable（状态与纯函数混放，子组件难复用） | 纯函数可独立单测，聚合/拆分/校验是核心业务规则 |
| 3 | `liveRemaining`/`onQtyInput` 归属 | 仅 CartPanel 子组件（DOM/展示局部） | 提入模型 | 模型只放父子共用或纯业务函数，避免万能工具模块 |
| 4 | `splitQty`/`rowQty`/`isRowInvalid` 归属 | 模型（父汇总+提交与子单元格校验共用） | 复制两份 | 单一事实源，口径必须一致 |
| 5 | 左栏搜索关键字状态 | 父组件持有，`v-model:keyword` 下传 | 关键字进子组件（父组件手机端 Tab 需要 filteredPickGroups.length 计数） | 计数依赖关键字，状态上提最简 |
| 6 | 单元格 `r.input.*` 变更方式 | 响应式对象嵌套直改（Vue 允许） | 每次按键 emit 上报（事件风暴） | 保持既有 v-model 交互模型，桥接成本最低 |
| 7 | 测试保障 | 存量 17 个全绿 + 模型单测 + 双子组件测试 | 仅存量 | 三层覆盖，重构安全网最厚 |
| 8 | 新文件位置 | `components/` 平级 | 子目录 `components/shipDialog/` | 沿用现有平级约定，减少 import 路径变更 |

## Surface

**新增 `shipCartModel.ts`**：导出类型 `PickGroup` / `OrderOption` / `MergedInput` / `CartProcessRow` / `CartProduct`；纯函数 `mergeKey` / `productRows` / `buildOrderOptions` / `buildPickGroups` / `buildCartGroups` / `splitQty` / `rowQty` / `isRowInvalid`。注意 `buildCartGroups` 会向传入的 `mergedInputs` Map 写入默认值（跨重算保持输入稳定的既有行为，非纯副作用，需在函数注释声明）。

**新增 `OutsourceShipPickPanel.vue`**：props `groups`（已过滤）与 `v-model:keyword`；emits `toggle(g)`、`select-all`。内部仅渲染卡片列表与搜索框，选择状态经 `selectedNames` prop 展示。

**新增 `OutsourceShipCartPanel.vue`**：props `groups: CartProduct[]`；emit `remove(productName)`。内部持有 `liveRemaining` / `onQtyInput` 及卡头合计渲染。

**主文件瘦身**：保留 UiDialog 壳、加载/结果态、手机 Tab、状态 refs、`load()`（改调模型聚合函数）、选择处理器、汇总 computeds、`submit()`、底栏三态。样式仅保留壳级（底栏/遮罩/结果态/响应式），左右栏样式随子组件迁移。

**测试**：`src/test/shipCartModel.test.ts`（聚合/拆分/校验/实时剩余边界）、`src/test/OutsourceShipPickPanel.test.ts`（toggle/select-all 事件、空态）、`src/test/OutsourceShipCartPanel.test.ts`（数量纠正：小数取整/0/超限、invalid 样式、remove 事件、空态）。

## Risks & Open Questions

- 存量 17 个测试直接 mount 父组件且查询 `.osw-card`/`.osw-cell`，子组件渲染后选择器应仍命中（真实子组件而非 stub）；若个别用例依赖内部实现细节需微调 mount 方式，断言本身不得放松
- `buildCartGroups` 对 `mergedInputs` 的写入副作用从 computed 迁入纯函数，需保证同一响应式 Map 引用传入，否则输入状态跨重算丢失
- 手机端双 Tab 布局依赖 `.osw-panes[data-tab]` CSS 选择器，子组件化后左/右栏类名必须原样保留

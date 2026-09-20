---
design_type: feature
created_at: 2026-09-20
---

# 发货清单工序数据展示：订单总量与实时剩余

## Intent Contract

```
intent: 在发货清单的每个工序格中展示该工序的订单总量与剩余未发数量，且剩余数量随用户填写的本次发货数量实时递减。
constraints:
  - 不改变提交契约与数量拆分口径（仍按订单生成发货单）
  - 不改变左栏聚合、搜索、全选逻辑
  - 不新增后端接口：复用 shippable 已返回的 target_qty / shipped_qty / remaining
  - 不改变既有校验规则（数量 > 剩余合计时标红阻断）
  - 保持单行横向滚动布局
success_criteria:
  - 每格显示「总量」= 该工序跨订单 target_qty 之和
  - 每格显示「剩」= 剩余合计 − 本次填写数量，且随输入框实时更新
  - 工序取消勾选时，「剩」回到剩余合计（不扣减）
  - 输入数量等于剩余合计时，「剩」显示 0
  - 既有 16 个回归测试全部通过
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests: npx vitest run src/test/OutsourceShipDialog.test.ts
  - check: 每格 .osw-total 文本等于该工序跨订单 target_qty 之和；.osw-remain 文本随输入框变化
  - check: 取消勾选后 .osw-remain 恢复为剩余合计
  - run: npm run type-check（本文件无新增报错）
  - confirm: 浏览器实测「Nommi糯米儿」6 道工序总量 10,130,600 对应各工序、剩余随输入实时递减
```

## Governance Contract

```
approval_gates:
  - 设计确认后方可实施（本文件）
  - 布局在 1080px 视口下的实测结果需回报用户
rollback: git checkout -- frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue frontend-vite/src/test/OutsourceShipDialog.test.ts
ownership: 前端发货模块维护者
```

## Scope

| 范围 | 内容 |
|---|---|
| In | 工序格新增「总量」显示 |
| In | 工序格「剩」改为实时值（剩余合计 − 本次填写） |
| In | 同步更新受影响的测试断言 |
| Out | 后端接口与查询（字段已存在，无需改动） |
| Out | 提交逻辑、数量拆分、校验规则 |
| Out | 已发数量（shipped_qty）的展示（本次需求未要求） |

## Decisions

| # | 决策 | 选择 | 否决的替代方案 |
|---|---|---|---|
| 1 | 「剩余」口径 | 本次发完后剩余 = 剩余合计 − 本次填写（实时预览） | 仅显示后端静态剩余（无法预览发完后结果）；两者同时显示（格子过窄，信息冗余） |
| 2 | 「总量」口径 | 跨订单 target_qty 之和 | 单订单 target_qty（合并行无意义）；仅显示已发（未覆盖需求） |
| 3 | 排布方式 | 格内固定堆叠两行（总量一行、剩余一行） | 并排两列（152px 格宽下两个 7 位数约需 200px，必然换行，布局不可预测）；加宽格子（增加横向滚动距离） |
| 4 | 超发显示 | 钳制为 0（非法输入已由红色边框与阻断提示表达） | 显示负数（对操作员不直观） |

## Surface

**组件**：`OutsourceShipDialog.vue` 的工序格（`.osw-cell`）。在「勾选框+工序名」与数量框之间新增统计区，展示总量与实时剩余。

**数据**：`CartProcessRow` 新增 `targetQty`（跨订单 target_qty 之和）。新增一个纯函数按「剩余合计 − 本次填写」计算实时剩余，未勾选时不扣减。

**样式**：新增统计区与两个数值的样式；`shipped_qty` 不参与本次展示。

**测试**：`OutsourceShipDialog.test.ts` 新增断言覆盖总量显示、实时递减、取消勾选恢复；既有断言中「剩」的取值改为实时值。

## Risks & Open Questions

- **格子高度增加**：新增一行统计后格子由 3 段变 4 段，高度约增加 16px。因单行横向滚动，不影响布局宽度，仅增加纵向占用。
- **两数值换行**：152px 格宽下「总量 1,907,520」与「剩 1,907,520」同排约需 170px，预计自动换行为两行。已在决策 #3 中接受，实施后以实测确认。
- **口径提示**：「剩」为发完后预览值而非后端静态值，可能被误读。缓解：数值为 0 时以弱化样式呈现，并在工序格 title 悬浮提示中说明「剩余合计 − 本次发货」。

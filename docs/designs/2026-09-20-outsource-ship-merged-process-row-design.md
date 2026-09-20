---
design_type: feature
created_at: 2026-09-20
---

# 批量发货清单：同一 SKU 的工序合并到一行展示

## Intent Contract

```
intent: 发货清单中每个 SKU 只占一行，该 SKU 的全部工序在这一行内横向排列，每道工序保留独立的数量输入框与剩余量显示。
constraints:
  - 不改变提交契约：仍按订单生成发货单，后端 ship-multi 接收扁平 items 列表
  - 不改变数量拆分口径：合并行填写跨订单合计，提交时按订单顺序依次填满各订单剩余量
  - 保留每道工序的独立勾选/取消（不发该工序）
  - 保留卡头「SKU 名 + N 单合并 + 合计件数 + ✕ 移出」
  - 保留左栏按产品名聚合、搜索筛选、全选
success_criteria:
  - 同一 SKU 的全部工序渲染在同一个横向容器内，SKU 名只出现一次
  - 宽屏（弹窗 1600px）下 6 道工序单行完整显示
  - 窄屏（视口 1080px）下自动换行，不产生横向溢出或遮挡
  - 每格含勾选框、工序名、剩余量、独立数量框四项
  - 既有回归测试更新后全部通过
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests: npx vitest run src/test/OutsourceShipDialog.test.ts
  - check: 每个 SKU 卡片内只有一个工序容器；容器 display 为 flex 且允许换行；工序格数量等于该 SKU 的去重工序数
  - check: 数量拆分口径不变——填 250 且各订单剩余 100/200/300 时，payload 为 PO-A 100、PO-B 150
  - run: npm run type-check（本文件无新增报错）
  - confirm: 浏览器实测 1080px 与宽屏下布局均无溢出，数量框可独立编辑且互不影响
```

## Governance Contract

```
approval_gates:
  - 设计确认后方可实施（本文件）
  - 布局在两种视口下的实测结果需回报用户
rollback: git checkout -- frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue frontend-vite/src/test/OutsourceShipDialog.test.ts
ownership: 前端发货模块维护者
```

## Scope

| 范围 | 内容 |
|---|---|
| In | 右栏工序行的布局：从「每工序一行」改为「每 SKU 一行、工序横向排列」 |
| In | 左栏收窄以给右栏让出宽度 |
| In | 同步更新受影响的选择器与测试断言 |
| Out | 提交契约、数量拆分算法、后端接口 |
| Out | 左栏聚合口径、搜索、全选逻辑 |
| Out | 发货单列表页与明细弹窗 |

## Decisions

| # | 决策 | 选择 | 否决的替代方案 |
|---|---|---|---|
| 1 | 行布局 | 每个 SKU 一行，工序在行内横向排列 | 保持每工序一行（行数过多）；所有工序共用一个数量框（与「每工序独立输入」冲突） |
| 2 | 每格内容 | 勾选框 + 工序名 + 剩余量 + 数量框 | 剩余量仅悬浮提示（用户明确要求可见） |
| 3 | 超宽处理 | 横向排列 + 自动换行，同时收窄左栏加宽右栏 | 横向滚动（6 道工序需拖动才能填完）；不收窄左栏（右栏过窄） |
| 4 | 单元格方向 | 格内纵向三段（勾选+工序名 / 剩余量 / 数量框） | 格内横向单行（单格需约 190px，同样宽度下可容纳的格数更少） |

## Surface

**组件**：`OutsourceShipDialog.vue` 右栏。工序行容器由纵向列表改为 `display:flex; flex-wrap:wrap` 的格子容器，每个工序一个格子；左栏宽度由 520px 收窄至 360px，腾出的宽度归右栏。

**数据**：`CartProcessRow` 结构不变（仍含 `processType`、`entries`、`remaining`、`input`）。本次仅改渲染层，脚本逻辑（合并、拆分、校验、提交）保持原样。

**样式**：新增工序格样式；移除原逐行样式与移动端对应规则；移动端格子改为整行堆叠。

**测试**：`OutsourceShipDialog.test.ts` 中依赖逐行结构的选择器改为格子选择器，断言值（行数/工序名序列）按新布局校准。

## Risks & Open Questions

- **窄屏无法单行**：6 道工序横排需约 1140px，视口 1080px 时右栏仅约 612px，必然换行。此为物理约束，非实现缺陷；宽屏下可单行。已在验收标准中区分两种视口。
- **左栏收窄的副作用**：最长产品名 20 字，在 360px 左栏下可能折为两行，属可接受退化。
- **待确认**：是否需要为工序格设置最大宽度上限，避免仅 1-2 道工序时格子被拉得过宽（当前设计未设上限，待实测后决定）。

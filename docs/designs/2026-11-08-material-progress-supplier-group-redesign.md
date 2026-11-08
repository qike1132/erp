---
design_type: redesign
created_at: 2026-11-08
---

# /material「物料进度（按供应商分组）」改版设计

> **已废弃（2026-11-08 同日）**：owner 判定「UI 逻辑完全不行」。本方案在没有约定交期的数据上
> 造了「逾期」概念，且把时间风险与数量进度混在同一列；三层卡片牺牲了可比较性。
> 现行方案见 `2026-11-08-material-progress-table-redesign.md`（扁平行列表 + 分组为视图模式）。

## Intent Contract

```
intent: 重做 /material 来料进度页的「物料进度（按供应商分组）」区域：把 7 列横向表格改成
        「一单一卡 + 供应商分组清单」，让用户一眼看清每个供应商的整体进度，并快速识别
        逾期物料与待收事项。
constraints:
  - 业务功能与数据不变：不改 useMaterialRegistrations 的合并/分组/逾期判定，不改后端接口与导出
  - ProgressTab 的 props/emits 契约不变（MaterialView 无需改动）
  - 状态四档（未开始/进行中/已到齐/逾期）必须同时给颜色与文字，不依赖颜色单独传达
  - 逾期口径仍为后端 30 天口径（登记日期 < 今天-30 且未收齐）
  - 只改 ProgressTab.vue / SupplierGroupCard.vue 与其结构断言测试
success_criteria:
  - npm run type-check 零错；npm test 全量通过
  - 1440 / 1024 / 768 / 390 四个宽度均无横向滚动，物料名不被无谓截断
  - 订单层可见「供应商数 / 待收项数 / 逾期项数 + 总进度」
  - 供应商层可见「状态词 + 已到 x/y 项 + 进度条 + 百分比」
  - 供应商块默认展开，整行可点且键盘可操作
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run: cd frontend-vite && npx vue-tsc --noEmit
  - run: cd frontend-vite && npm test
  - run: npx eslint src/views/material/components/ProgressTab.vue src/views/material/components/SupplierGroupCard.vue
  - 视觉: dev server 起在 127.0.0.1:5199 + page.route 注入 /api/v1/** 夹具，
         在 1440/1024/768/390 四个视口截图核对（生产页面需登录，禁止直连生产 API）
  - 变异: 去掉 statusKey 的 overdue 分支、把「有逾期」筛选改成不过滤，对应测试必须变红
```

## Governance Contract

```
approval_gates:
  - 设计文档（本次）
  - 合并前 code-review（推送前一次）
rollback: 两文件 + 测试的局部改动，git 还原即可；不涉及迁移、接口与数据
ownership: 来料登记模块负责人
```

## Scope

| In | Out |
| --- | --- |
| ProgressTab.vue 列表容器与订单头 | 改动 useMaterialRegistrations（数据口径） |
| SupplierGroupCard.vue 供应商行与物料行 | 改动 MaterialToolbar（KPI / 搜索 / 导出） |
| 本页异常筛选（全部 / 有逾期 / 未开始） | 改动后端接口、导出、收货流程 |
| 分页改用共享 UiPagination | 全局主题与设计变量 |

## Decisions

| # | 决策 | 选择 | 被否方案 | 理由 |
| --- | --- | --- | --- | --- |
| D1 | 列表形态 | 订单卡片 + 分组清单 | 保留 UiDataTable 只换列 | 7 列在 1024px 就被截断，客户/产品名逐字换行；卡片可自然换行，无需横向滚动 |
| D2 | 总进度 | 并入订单头（条 + %） | 保留独立「总进度（按供应商分段）」列 | 分段条只能靠颜色和供应商块对应，用户要来回对照；并入后订单摘要与明细同处一屏 |
| D3 | 状态图例 | 删除顶部图例条 | 保留四色图例 | 每个供应商行都带状态词，图例只是重复一行的视觉噪音 |
| D4 | 供应商行进度条 | 组头一根，与物料条共用列轨道 | 组头迷你条 + 物料条（各一根） | 同源信息画两遍；共用轨道后纵向可扫读 |
| D5 | 供应商数量聚合 | 只给「已到 x/y 项」 | 已到 / 采购 数量合计 | 组内物料单位不同（码/只/张），跨单位数量求和无意义 |
| D6 | 进度条宽度 | 封顶 180px，名称列吃剩余空间 | 条自适应铺满 | 铺满时条成为横贯整行的大色块，压掉名称可读性 |
| D7 | 异常筛选 | 本页三档筛选（全部 / 有逾期 / 未开始） | 不做筛选 / 服务端筛选 | 服务端无此参数；搜索已是本页口径，保持一致并在空态与提示中写明「本页」 |
| D8 | 同一供应商多张登记 | 不合并，按登记日期分别成块 | 按供应商名合并 | 逾期判定按登记日期，合并会抹掉「哪一批超期」；多条登记时靠登记日期区分 |

## Surface

**前端组件**（2 文件 + 1 测试）：
- `frontend-vite/src/views/material/components/ProgressTab.vue`：列表容器（`.mr-orders` / `.mr-order`）、订单头（`.mr-order-head`，含 `.mr-sum` 摘要与 `.mr-order-progress`）、本页筛选（`.mr-filterbar` / `.mr-filter`）、骨架屏（`.mr-skel`）、空态（`.mr-empty`）、分页（`UiPagination`，1 基页码 ↔ 父级 0 基 `page` 事件）。
- `frontend-vite/src/views/material/components/SupplierGroupCard.vue`：供应商行（`.mr-grp-head`，`role=button` + `aria-expanded`，Enter/Space 可切换）与物料行（`.mr-mat`），共用列轨道 `minmax(0,1.5fr) minmax(96px,auto) minmax(110px,180px) 46px 20px`；状态左轨与 `.mr-chip` 同源 `--st`。
- `frontend-vite/src/test/materialProgressRedesign.test.ts`：数据层断言（合并/分组/逾期/搜索）保持原样；组件层断言改为新结构，并新增键盘可达、本页筛选、分页 0 基换算、骨架屏。

**断点**：≥861 单行五列；≤860 供应商/物料行降为两行网格（条独占一行）；≤520 订单头纵排、项数让位给名称。

## Risks & Open Questions

- `pCount` 是后端「登记条数」，与页面上的订单卡数量不是 1:1（同单多条登记会合并）。分页量词沿用「条登记」，避免让人以为卡片数=总数。
- 本页筛选与搜索同为本页口径，翻页后结果变化；空态文案已写明「本页…可翻页查看其他页」。
- 已收齐的供应商块仍默认展开（保持历史行为）。若后续认为已完成块应默认收起，需同步更新 `collapsedGroups` 的三态语义与测试。

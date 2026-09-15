# 下单查询 TAB 前端交互优化方案

> 页面：`http://192.168.0.95:3000/purchase` → Tab「下单查询」
> 基线 commit：`cce3a7b`
> 分析日期：2026-09-14

---

## 一、结论摘要

| 维度 | 现状评分 | 核心问题 |
|---|---|---|
| 交互体验 | **D**（不合格） | 三层筛选/导出 UI 被删除后**未重做**，状态层代码残留成死代码；表格行不可聚焦、不可键盘操作、无可发现的行操作入口 |
| 视觉呈现 | **C+** | 表头与列宽存在硬编码魔数（`padding-right:116px`），`fetching` 进度条被 `<table>` 挡住的布局风险；状态徽章 4 色 + 未映射兜底 |
| 性能表现 | **B−** | 后端分页 20 行/页已合理，但 `perPage` 常量与 UI 无联动；`fetching` 期间整表保留旧数据却无「数据陈旧」提示；`keepPreviousData` 与骨架屏语义冲突 |

**一句话诊断**：这是一个**后端能力完备、但前端把能力删掉了的查询页**。用户目前只能翻页，无法按订单号/客户/产品/日期查询，无法导出。这不是"体验不够好"的问题，而是**核心查询功能缺失**的问题。

---

## 二、能力链路断点（根因分析）

commit `be36f57`（2026-09-12）以「下单查询移除筛选区与标题」为标题，一次性删除了 3 个组件：

| 被删组件 | 行数 | 承载能力 |
|---|---|---|
| `CompletedOrdersSearchBar.vue` | 245 | 订单号 / 客户名称 / 产品名称输入 + 起止日期选择 + 查询按钮 + 快速筛选 chips |
| `CompletedOrdersAdvancedFilter.vue` | 175 | 供应商 / 69码 / 物料名称 输入 + 重置 |
| `CompletedOrdersToolbar.vue` | 122 | 标题 + 条目数 + 高级筛选折叠 + 导出按钮 |

**关键问题**：删除了 UI，但**没有删除状态层**。`useCompletedOrders.ts`（231 行）中的以下 API 至今保留且已接入 `queryKey`：

```ts
filters                  // 8 个筛选字段，已参与 queryKey → 生效
quickFilters             // 快速筛选
applyQuickFilter(id)     // 应用快捷筛选
resetFilters()           // 重置
exportOrders()           // 导出（完整实现了 Blob 下载）
loadQuickFilters()
```

在 `PurchaseView.vue:111-123` 中，`CompletedOrdersPanel` 只接收 `orders/loading/fetching/error/total/currentPage/totalPages` 七个 props，**`filters`、`quickFilters`、`exportOrders` 等全部未传入**。`CompletedOrdersPanel.vue` 中 `grep filters|quickFilters|export` 结果为空。

→ **结论：筛选与导出能力在组件树中完全不可达，属功能性缺失。**

### 附加发现：`quick-filters` 存在类型契约不一致

- **后端**（`fastapi_app/schemas/purchase_center.py:330`）：`quick_filters: dict[str, int]`，实际返回 `{today: N, week: N, month: N}`（见 `purchase_order_query.py:500`）
- **前端**（`src/api/purchase.ts:73` + `useCompletedOrders.ts:9`）：声明为 `{id, name, filters:{start_date, end_date}}[]`

两者形状完全不同。`applyQuickFilter()` 内部执行 `quickFilters.value.find(f => f.id === filterId)`，而 `dict` 上不存在 `.find()` → **一旦被调用必然抛错**。也就是说即便当初 UI 还在，快速筛选也是坏的。重新设计时必须修掉。

---

## 三、逐维度问题清单

### 3.1 交互体验

| # | 问题 | 证据 | 影响 |
|---|---|---|---|
| I-1 | **无任何筛选入口**（P0） | `PurchaseView.vue:111-123` 未传 filters；3 个筛选组件已删 | 无法按订单号/客户/产品/日期查询，只能逐页翻找 |
| I-2 | **无导出入口**（P0） | `exportOrders()` 有实现但零调用点 | `POST /completed/export` 成废接口，用户只能手工抄数据 |
| I-3 | **无条目总数展示** | `CompletedOrdersTable.vue` 未渲染 `total` 到页面可见处（仅 `UiPagination` 内部显示） | 用户不知道结果集规模 |
| I-4 | 表格行**不可键盘聚焦** | `CompletedOrdersTable.vue:36-41` `<tbody @click>`，无 `tabindex`、无 `@keydown` | 键盘用户无法打开详情，违反 WCAG 2.1 AA |
| I-5 | 行操作**不可发现** | 整行 `cursor:pointer` 但无「查看详情」按钮/图标，仅靠鼠标悬停背景色暗示 | 新用户不知道可以点击 |
| I-6 | `error` 与 `empty` **判定冲突** | `useCompletedOrders.ts:214,216` 同时传 `loading: isLoading` 与 `fetching: isFetching`；表格里 `v-else-if="error && orders.length === 0"` 与 `v-else-if="orders.length === 0"` | 已有数据时出错 → 静默无提示（仅 toast 一闪） |
| I-7 | **空状态无引导** | `CompletedOrdersTable.vue:16-19` 仅「暂无订单记录」 | 无法区分「真的没数据」与「筛选过窄」，无清空引导 |
| I-8 | 分页**缺少每页条数与跳页** | `CompletedOrdersTable.vue:67-72` 未传 `pageSize`/`pageSizeOptions` | `UiPagination.vue:57` 的 `showSizeSelector` 因 `pageSize == null` 判为 false；大结果集只能连点下一页 |
| I-9 | 无刷新入口 | 页面无手动刷新按钮 | 数据陈旧时只能靠 30s 轮询或 F5 |
| I-10 | `filters` 字段名与 UX 不符 | 用 `order_no` 单字段却无对应输入框 | 8 个筛选字段中 6 个无 UI |

**关于过滤方式的判断**：原实现是「输入即改 `filters` → 立即触发 `queryKey` 变化 → 每次按键都发请求」，再配一个「查询」按钮（语义矛盾：既然即时生效，查询按钮无意义）。**重新设计应改为显式提交 + 防抖组合**，避免每键一请求，也避免「查询」按钮形同虚设。

### 3.2 视觉呈现

| # | 问题 | 证据 |
|---|---|---|
| V-1 | **表头 `padding-right: 116px` 魔数** | `CompletedOrdersTable.vue:178,181` — `th.coq-w-num { padding-right: 116px }`、`.coq-td-num { padding-right: 116px !important }`。删除了「操作」列后未收回，导致数量列右对齐位置异常靠左 |
| V-2 | **`fetching` 进度条位置错误风险** | `CompletedOrdersTable.vue:23` 的 `.coq-fetching` 是 `<template>` 内的普通 `div`，位于 `.coq-table-scroll`（`overflow-x:auto`）**之前**；而 `ActiveOrdersPanel.vue` 放在 `.pc-section-body` 内。两个面板层级不一致，出现位置会漂移 |
| V-3 | 状态徽章**有未映射兜底但语义丢失** | `CompletedOrdersTable.vue:100-105` `statusMap` 只覆盖 4 态；后端 `PurchaseOrderStatus` 仅产生 `pending`/`completed`（`shared_models/purchase_order.py:19-28`），`partial`/`cancelled` 永不出现 → 死分支；反之未映射态显示英文原文 |
| V-4 | **完成时间粒度损失** | 后端返回 `completed_at: 'YYYY-MM-DD HH:mm'`，`formatDate()` 用 `Intl.DateTimeFormat` 只保留年月日 → 同一天的多笔订单时间显示完全相同 |
| V-5 | **`sku_items` 的 `barcode` 未渲染** | `types/index.ts:212-218` 有 `barcode`；`_list.py:253` 后端确实返回；但 `getSkuRows()` 只取 `product_name` + `quantity`（`CompletedOrdersTable.vue:115-120`）→ 69码列缺失，而 69 码是筛选键 |
| V-6 | 供应商信息**不可见** | 客户列有，供应商列无。但筛选维度里 `supplier_name` 存在且导出包含 → 用户筛了却看不到 |
| V-7 | 表头 `text-transform: uppercase` **对中文无效** | `CompletedOrdersTable.vue:153` — 中文表头无大小写，该规则只影响 `SKU` 等拉丁字符 |
| V-8 | 骨架屏行高 42px **与真实行高不匹配** | `.coq-skeleton-row { height: 42px }` vs 真实 `td padding:10px + 13px 行高 ≈ 33px`（单 SKU 行）；多 SKU 行更高 → 加载完成瞬间高度跳变 |

### 3.3 性能表现

| # | 问题 | 证据 | 评估 |
|---|---|---|---|
| P-1 | 分页参数**硬编码且与 UI 脱节** | `useCompletedOrders.ts:51` `per_page: 20` 写死在两处（主查询 + prefetch），UI 无法调整 | 中 |
| P-2 | `keepPreviousData` 与骨架屏**语义冲突** | `placeholderData: keepPreviousData` 会让 `data` 保留旧值 → `orders.length !== 0` → `v-if="loading && orders.length === 0"` 为假 → 翻页时**永不显示骨架**，只显示顶部细进度条 | 低（体验尚可，但与代码意图不符） |
| P-3 | `fetching` 期间**无「数据陈旧」提示** | 顶部 `coq-fetching-bar` 仅 2px 细条，用户可能忽略 | 低 |
| P-4 | `flatRows` computed 正确但**未做 key 稳定性优化** | `:key="row.o.id + '-' + idx"` 用索引拼接，SKU 数量变化时会重建 DOM | 低 |
| P-5 | **20s 超时兜底逻辑在三处重复** | `useCompletedOrders.ts:73-92`、`usePurchaseOrders.ts:43-62`、`useUnprocessedOrders.ts:56-75` 完全相同 | 低（可维护性） |
| P-6 | `staleTime 30s` + `gcTime 60s` **偏短** | 结合 `keepPreviousData`，返回列表时大概率重新请求 | 低 |
| P-7 | 分页 **offset/limit 深翻页** | 后端 `query.offset((page-1)*per_page).limit(per_page)`（`purchase_order_query.py:139`） | 低（数据量万级，`per_page` 上限 500，当前无风险） |

**性能结论**：本 TAB 的性能**不是主要矛盾**。20 行/页的服务端分页 + `prefetchQuery` 预取下一页已足够。原 `per_page:20` 合理。**不建议引入虚拟滚动**（20 行/页无收益，且会破坏 `rowspan` 合并单元格结构）。优化重点应放在**感知性能**（骨架屏、陈旧提示、命中高亮）而非绝对性能。

---

## 四、优化方案

### 设计原则

1. **恢复即重做**——不复用被删的 3 个组件（原实现存在「即时生效 vs 查询按钮」语义矛盾），按新交互范式重新实现
2. **后端零改动**——7 个筛选参数、导出接口、分页接口全部已就绪，纯前端交付
3. **收口状态层**——清理 `useCompletedOrders.ts` 死代码，修正 `quick_filters` 类型契约
4. **可访问性达 AA**——键盘可达、aria 标注、焦点可见

### 4.1 目标交互模型

**核心变化：把「8 个输入框平铺」压缩为「一个搜索框 + 快捷 chips + 可折叠高级筛选」，并用「条件 pills」让已生效条件始终可见可撤销。**

```
┌─ 下单查询 ──────────────── 共 342 条 ──── [高级筛选 ▾] [刷新] [导出 Excel] ─┐
│  ⌕ 搜索订单号 / 客户 / 产品…（按 / 聚焦）    [全部 342][今天 12][近7天 68][近30天 214] │
│  ● 关键词: 保温杯 ✕  ● 客户: 杭州晨光 ✕  ● 近 7 天 ✕        清空全部条件      │
│  ┌─ 高级筛选（折叠） ─────────────────────────────────────────────┐        │
│  │ 客户名称  供应商  69码  物料名称  完成时间从  完成时间到              │        │
│  │ [应用筛选] [重置全部]                                            │        │
│  └──────────────────────────────────────────────────────────────┘        │
├─────────────────────────────────────────────────────────────────────────┤
│  完成时间       客户 / 供应商      69码        数量    状态      操作        │
│  2026-09-14   杭州晨光贸易      6901234…     1,200   已完成   [查看详情]    │
│  09:12        宁波精工塑业      ┃              800            ↑hover显现 │
└─────────────────────────────────────────────────────────────────────────┘
```

**关键交互决策**

| 决策 | 内容 | 理由 |
|---|---|---|
| 提交策略 | 关键词 **300ms 防抖**；高级筛选 **显式点「应用筛选」** | 关键词即时反馈符合直觉；高级筛选字段多、需组合，显式提交避免每键一请求 |
| 快捷 chips | `全部 / 今天 / 近7天 / 近30天`，带计数，点击即生效 | 覆盖 80% 高频查询；修掉原 `dict` vs `array` 类型错 |
| 条件 pills | 所有生效条件渲染为可单点撤销的胶囊，含「清空全部条件」 | 解决「筛了但忘了筛了什么」——这是原实现最痛的可用性缺口 |
| 空状态 | 区分「无数据」与「条件过窄」，后者给「清空全部条件」按钮 | 消除用户卡死在空列表的死角 |
| 行操作 | 整行可点 **+** hover 显现「查看详情」按钮 **+** `tabindex="0"` + Enter 触发 | 可发现性 + 键盘可达 |
| 列调整 | 新增 `供应商` 与 `69码` 两列；`数量` 改为汇总值 | 匹配筛选维度，消除「能筛不能看」 |
| 分页 | 启用每页条数（20/50/100）+ 跳页 | 后端 `per_page` 上限 500，直接可用 |

### 4.2 涉及文件清单

#### 新建（4 个）

| 文件 | 职责 | 预估行数 |
|---|---|---|
| `src/views/purchase/components/CompletedOrdersToolbar.vue` | 标题 + 条目数 + 高级筛选折叠 + 刷新 + 导出。导出按钮内置 loading 态与 disabled 防重 | ~130 |
| `src/views/purchase/components/CompletedOrdersFilterBar.vue` | 统一搜索框（防抖 + `/` 快捷键 + 清除）+ 快捷 chips + 条件 pills + 可折叠高级筛选面板 | ~300 |
| `src/views/purchase/components/CompletedOrdersEmpty.vue` | 空状态组件：区分「无数据」/「条件过窄」，后者提供清空按钮 | ~70 |
| `src/views/purchase/components/completed-orders.scss` | 从 `CompletedOrdersTable.vue` 抽出共用样式，供 Toolbar/FilterBar/Table 共享（对齐现有 `order-panels.scss` 模式） | ~200 |

#### 修改（5 个）

| 文件 | 改动 |
|---|---|
| `frontend-vite/src/views/purchase/composables/useCompletedOrders.ts` | ① 修正 `QuickFilter` 类型为 `Record<string, number>` 并重写 `applyQuickFilter` ② `perPage` 改为 `ref` 并接入 `queryKey` ③ 新增 `activeFilterCount` / `hasActiveFilter` computed ④ 新增 `keyword()` 防抖入口 ⑤ 抽出 `buildParams()` 消除主查询/prefetch/导出三处参数拼装重复 ⑥ `start_date/end_date` 互斥校验 |
| `frontend-vite/src/views/purchase/components/CompletedOrdersTable.vue` | ① 删除 `padding-right:116px` 魔数 ② 新增供应商列、69码列 ③ `formatDate` → `formatDateTime` ④ 行加 `tabindex="0"` + `@keydown.enter` ⑤ 状态徽章收敛为后端真实 2 态 + 兜底 ⑥ 骨架屏行高对齐真实行高 ⑦ 引入 `CompletedOrdersEmpty` ⑧ 分页传 `pageSize`/`pageSizeOptions` ⑨ 关键词命中高亮 |
| `frontend-vite/src/views/purchase/components/CompletedOrdersPanel.vue` | 组装 Toolbar + FilterBar + Table；新增透传 props（`filters`/`quickFilters`/`currentQuickFilterId`/`perPage`）与 events（`updateFilter`/`applyQuickFilter`/`resetFilters`/`search`/`export`/`refresh`/`update:perPage`） |
| `frontend-vite/src/views/purchase/PurchaseView.vue` | 给 `CompletedOrdersPanel` 补齐 props 与事件绑定；header-actions 区接导出/刷新（保持与「待生产订单」TAB 同位置） |
| `frontend-vite/src/api/purchase.ts` | 修正 `quickFilters()` 返回类型为 `{ quick_filters?: Record<string, number> }`；`completed()` 参数类型收紧 |

#### 测试（2 个）

| 文件 | 内容 |
|---|---|
| `src/test/completedOrders.filter.test.ts`（新建） | `buildParams()` 参数拼装正确性；`resetFilters` 清空全部 8 字段；`applyQuickFilter` 对 `Record` 形状正确解析；日期区间互斥 |
| `src/test/CompletedOrdersTable.test.ts`（新建） | 错误态/空态/条件过窄三态渲染分支；行 `Enter` 触发 `viewDetail`；`pageSize` 变更触发 `update:pageSize`；多 SKU `rowspan` 正确 |

### 4.3 分阶段实施

| 阶段 | 内容 | 交付物 | 验收 |
|---|---|---|---|
| **P0** | 恢复筛选与导出能力；修 `quick_filters` 类型契约；修正表头魔数 | Toolbar + FilterBar | 可按订单号/客户/产品/日期/供应商/69码/物料查询；可导出 xls |
| **P1** | 可访问性与可发现性：行键盘可达、hover 行操作、`/` 快捷键、条件 pills、空状态引导 | Table + Empty | 纯键盘完成「查询→定位→打开详情」全流程 |
| **P2** | 感知性能与视觉：骨架屏行高对齐、陈旧数据提示、关键词高亮、状态徽章收敛、列补充（供应商/69码） | Table | 翻页无高度跳变；筛了能看见筛什么 |
| **P3** | 收口与防腐：抽 `buildParams`、抽 20s 超时 hook、补单测 | composable + test | `vue-tsc` 零错误；新增测试全绿 |

### 4.4 预期效果

| 指标 | 现状 | 优化后 |
|---|---|---|
| 可查询维度 | **0** | 8 个（关键词 + 客户 + 供应商 + 69码 + 物料 + 起止日期 + 快捷时段） |
| 定位一笔历史订单 | 逐页翻找，无上限 | 输订单号 → **1 次请求直达** |
| 导出 | **不可用** | 一键导出 xls，模板已实现 |
| 已生效条件可见性 | 无 | 条件 pills + 计数徽标 |
| 键盘可达性 | 不可达 | 全流程可达（含 `/` 聚焦搜索） |
| 空状态 | 单一文案 | 区分无数据/条件过窄 + 一键清空 |
| 单次查询请求数 | 1（仅翻页） | 关键词 300ms 防抖后 1 次；高级筛选显式提交 1 次 |
| 每页条数 | 固定 20 | 20/50/100 可选（后端上限 500） |

---

## 五、风险与约束

| 风险 | 说明 | 缓解 |
|---|---|---|
| **R1 需求意图未确认** | `be36f57` 标题是「移除筛选区」，可能是刻意简化 | ✅ 已与需求方确认：**彻底清理残留代码后重新设计**筛选/导出/查询 |
| R2 三处 20s 超时逻辑重复 | 本次仅下单查询可重构，另两处保留 | 抽 `useQueryTimeout` 通用 hook 后统一替换，需回归 `PurchaseView.autorefresh.test.ts` |
| R3 `raw` 分支响应式失效 | 新建 `Promise.all` 分支若在 `setup` 顶层解构会失去响应式 | 沿用现有 `computed(() => data.value?.orders ?? [])` 写法；评审时重点核对 |
| R4 后端返回结构不一致 | 列表返回 `pages`（`purchase_order_query.py:159`），`total_pages` 仅存在于类型声明 | composable 已兼容 `data.pages ?? data.total_pages`，保持不变 |
| R5 `quick_filters` 契约修复需确认后端语义 | 后端返回计数而非区间定义，前端需自行把 `today/week/month` 映射为日期区间 | 前端本地映射（`today` → `start=end=今天`；`week` → `start=今天-7d`）；**若后续需人工配置区间，须后端补 `name`/`filters` 字段** |
| R6 移动端 | `mobile/views/purchase/MPurchaseView.vue` 存在独立的 completed 分支 | 本次不动移动端；桌面端改造若改动 `useCompletedOrders` 返回值需同步检查移动端引用 |

---

## 六、附：可运行原型

原型文件：`deliverables/下单查询-proto/index.html`

**用法**：直接用浏览器打开。右上角切换「优化后 / 当前线上」可对比两版交互。

原型已实现（均可用真实交互验证）：
- 统一搜索框：300ms 防抖、`/` 快捷键聚焦、清除按钮、结果关键词高亮
- 快捷 chips：带计数、点击即筛选、激活态
- 高级筛选：可折叠面板、6 个字段、应用/重置
- 条件 pills：任意条件单点撤销 + 一键清空
- 表格：列排序（时间/数量）、多 SKU `rowspan` 合并、hover 显现「查看详情」、整行 Enter 可触发
- 三态：骨架屏（loading）/ 无数据空态 / 条件过窄空态（含清空按钮）
- 分页：每页 20/50/100 + 跳页 + 总条目数
- 导出按钮：loading 态 + 防重 + toast 反馈
- 响应式：≤820px 隐藏次要列、≤560px 按钮撑满

> 原型为**交互与视觉验证用**，数据为内置 mock，不代表真实接口字段。

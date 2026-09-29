# 生产驾驶舱重构设计（`/production`）

- 日期：2026-09-29
- 状态：待评审
- 路由：`/production`（PC）与同名移动端路由（手机自动切换）
- 关联代码：`frontend-vite/src/views/production/**`、`frontend-vite/src/mobile/views/production/**`、`fastapi_app/api/v1/endpoints/daily_production.py`

---

## 1. 背景与目标

### 1.1 现状

`/production` 是"每日生产报表"，覆盖三个部门（充棉部 / 手工部 / 包装部）。PC 端 10 个文件、2036 行，结构为 `ProductionView.vue`（283 行，编排层）+ 工具栏 / 日报面板 / 月报面板 / 录入弹窗 / 图表 composable。日报与月报两个 Tab，各自是"KPI 卡 + 部门卡 + 图表 + 表格"。

### 1.2 已确认的缺陷

按严重度排列，均已定位到代码行：

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| 1 | P0 | **生产明细完全不可见、不可改、不可删**。后端 `GET/PUT/DELETE /daily-production/records` 已支持按年/月/部门/日期筛选 + 分页（`per_page` ≤ 200）+ `stats`，前端 `dailyProductionApi.records / updateRecord / deleteRecord` 定义了但**零调用**，页面上没有任何记录列表。录错一条只能去数据库改。 | `fastapi_app/api/v1/endpoints/daily_production.py:38-157`；`frontend-vite/src/api/production.ts:20-27` |
| 2 | P0 | **月报两个头部 KPI 恒为 0**。面板读 `monthlySummary.overall_quantity`，后端只返回 `monthly_total_quantity`，`?? 0` 兜底掩盖了字段名不匹配。 | `ProductionMonthlyPanel.vue:5-6`；`fastapi_app/services/daily_production_service.py:399`；`frontend-vite/src/types/index.ts:428` |
| 3 | P0 | **导出与 Tab 语义脱节**。导出固定传 `start_date = end_date = selectedDate`，且不传 `department`；月报 Tab 点导出实际导出的是某一个单日。后端已支持日期区间 + 部门筛选。 | `ProductionView.vue:180`；`daily_production.py:214-252` |
| 4 | P0 | **KPI 只有绝对值，没有任何对比**，看不出趋势好坏。 | 全局 |
| 5 | P1 | 部门卡不可点，无下钻；SKU 维度缺席（只有"种数"）；日报图表把产量与产值两个量纲塞进双 Y 轴并排柱；月报无占比无对比；无骨架屏、无空态。 | `useProductionCharts.ts:50-83`；`ProductionDailyPanel.vue:14` |
| 6 | P2 | 硬编码色值（`#eff6ff/#1e40af/#f0fdf4` 等）遍布，未用 `--color-primary-*` token；日报与月报面板有约 90 行**逐字重复**的 CSS；`KpiCard.vue` 与共享 `UiStatCard.vue` 重复造轮子（`components/ui/` 下有 37 个共享组件，本页几乎一个未用）；手绘 toast 与 `showToast` 并存；`ProductionEntryDrawer` 实为居中模态，名实不符。 | `ProductionDailyPanel.vue:92-187` 与 `ProductionMonthlyPanel.vue:102-187` |

### 1.3 目标（成功标准）

1. 生产明细在页面上**可查、可筛、可改、可删**，录错可在前端自行修正。
2. 打开页面**一眼**看到：今日产量/产值、本月累计、近 30 日趋势、三部门当日表现 —— 无需切 Tab、无需滚动。
3. 每个数字都带**上下文**（较昨日 / 较上月 / 占比），不是孤立绝对值。
4. 导出与当前筛选语义一致，支持日期区间 + 部门。
5. 三类角色（车间主任 / 厂长老板 / 录单员）都能用，且**按部门限制可见范围**。
6. 视觉统一到全站 token，消除重复 CSS。
7. PC 与移动端口径一致。

### 1.4 非目标

- 不做同比（见 §3 D4）。
- 不做自定义看板 / 自由拖拽布局。
- 不改动 `production_summary.py`（工艺、包装记录）那些接口的行为（见 §9 R3）。
- 不做生产计划、工艺管理等新业务功能。

---

## 2. 范围

**在范围内**：`/production` 的 PC 端与移动端信息架构、视觉、交互重构；补齐明细 CRUD；按部门拆权限；为新视图所需的聚合接口。

**不在范围内**：数据模型变更（`daily_production_record` 表结构不动，含不做软删除）、`production_summary.py` 的工艺/包装接口、生产计划模块。

---

## 3. 设计决策记录

| # | 决策 | 选择 | 理由 | 被否方案 |
|---|---|---|---|---|
| D1 | 重构范围 | **生产驾驶舱大改**（跨前后端） | 只做视觉翻新无法解决"不全面"：明细不可见是功能缺口，不是样式问题 | 纯视觉翻新；仅补明细的折中方案 |
| D2 | 主要使用者 | **三种角色都要，按角色分** | 车间主任盯当日进度、厂长看月度趋势、录单员录入对账，三者关注点不同 | 单一角色优先 |
| D3 | 可见范围实现 | **按部门拆权限点**（新增 6 个码） | 不动 `user` 表结构；过滤逻辑只落在生产模块内（正是重构范围）；已有 `SPECIAL_PERMISSION_MAP` 先例（`outsource_manage`） | 给 `User` 加 `department` 字段（要动用户表 + 管理页 + 迁移）；本期不做隔离 |
| D4 | 对比口径 | **不做同比**，先做趋势 | 数据只上线几个月，同比位置会长期是空白 | 同比曲线 |
| D5 | 信息架构 | **一屏驾驶舱 + 下钻**（不分 Tab） | 跨视图对比无需来回切；"一眼看全"是驾驶舱的本意 | 四 Tab 平铺；左侧导航 + 内容区 |
| D6 | 主屏组织 | **固定布局，不做切换器** | 三角色的差异是*关注点*差异而非*视图*差异，四类信息同屏即可满足；切换器只带来空态与"导出的是哪一段"的歧义 | 时间范围切换；关注点切换；范围 × 视角双切换（9 种组合） |
| D7 | 下钻容器 | **全功能明细抽屉**（一个抽屉通吃） | 录单员要的"筛选+分页+批量"和车间主任要的"点一下看本部门"是同一张表、不同筛选条件；做成一个抽屉只需维护一套筛选/分页逻辑 | 下钻轻抽屉 + 独立明细视图（两套逻辑）；就地主屏展开（破坏一屏看全） |
| D8 | 视觉方向 | **V1 清爽蓝白**，统一到全站 token | 同时解决"层次不直观"与"色值散落"；与 ERP 其余页面零违和 | 深色顶栏驾驶舱（破坏一致性）；紧凑数据密集（密度用响应式解决即可） |
| D9 | 移动端 | **M2 精简（今日 + 部门）**；明细为全屏列表页 | 手机上一眼看全比看得多重要；趋势图在小屏读不出信息反而挤掉部门卡；全屏就是手机的抽屉，与 PC 共用筛选语义 | 完整移植（要滑两三屏）；录单/对账优先（看进度是手机最高频动作） |
| D10 | 移动端范围 | **PC + 移动一起改** | 两端口径一致 | 只改 PC；移动端只补明细 |

---

## 4. 信息架构

### 4.1 PC 主屏（固定布局，一屏不滚动）

```
┌ 工具栏 ─────────────────────────────────────────────────────┐
│ ‹  2026-09-29  ›  [今天]        [+ 录入] [导出] [明细]        │
├ ① KPI 条（4 格）───────────────────────────────────────────┤
│ 今日产量 4,250 件      今日产值 ¥27,170                      │
│ 较昨日 +12.4%          较昨日 +8.1%                          │
│ 本月累计 86.4 万件     日均产量 4.1 万件                     │
│ 21 个生产日            较上月 +3.2%                          │
├ ② 近 30 日趋势（左，约 2/3）│ ③ 本月部门排行（右，约 1/3）─┤
│ 按部门堆叠柱 + 合计折线    包装部 44.1万 ████████            │
│ 图例：充棉 / 手工 / 包装   充棉部 24.7万 █████               │
│                            手工部 17.6万 ████                │
├ ④ 三张部门下钻卡 ─────────────────────────────────────────┤
│ 充棉部 1,240 件 · ¥8,680 ›  手工部 860 件 ›  包装部 2,150 件 ›│
└───────────────────────────────────────────────────────────┘
```

**KPI 口径定义**（写入实现，避免歧义）：

| 指标 | 口径 | 数据来源 |
|---|---|---|
| 今日产量 / 今日产值 | 所选日期的 `overall_quantity` / `overall_value` | `GET /daily-summary?date=` |
| 较昨日 | `(今日 − 昨日) / 昨日 × 100%`；昨日为 0 时显示 `—` | 同上，取昨日 |
| 本月累计 | `monthly_total_quantity` / `monthly_total_value` | `GET /monthly-summary` |
| 生产天数 | `daily_data` 中 `total.quantity > 0` 的天数 | 同上 |
| 日均产量 | 本月累计 ÷ 生产天数（**分母是生产天数，非自然日**） | 同上派生 |
| 较上月 | `(本月日均 − 上月日均) / 上月日均 × 100%` | 同上，取上月 |

**关键修正**：`本月累计` 必须读 `monthly_total_quantity`，不得再读 `overall_quantity`（即 D-2 缺陷的修复点）。

### 4.2 明细抽屉（PC）

- **打开方式**：
  - 工具栏「明细」→ 不带筛选打开，默认日期范围 = 本月。
  - 点部门下钻卡 → 打开且**部门筛选已预置**为该部门（用户可改回「全部部门」）。
- **宽度**：约 1000px（占主屏约一半），右侧滑出，主屏保持可见。
- **筛选**：日期范围（今日 / 本周 / 本月 / 自定义）、部门、产品名或 69 码搜索、录单人。
- **表格列**：日期 | 部门 | 产品名 | 69 码 | 数量 | 单价 | 产值 | 备注 | 录单人 | 操作。
- **行操作**：改（弹窗，复用录入表单）、删（二次确认）。
- **批量**：勾选多条 → 批量删除（见 §6.5 护栏）。
- **分页**：默认 50 条/页，与后端 `per_page` 对齐。
- **合计**：抽屉底部或顶部固定显示当前筛选下的条数与合计产量/产值（使用后端 `stats`）。

### 4.3 旧「日报 / 月报」的映射

新设计取消了 Tab，原两 Tab 内容的去向：

| 原内容 | 去向 |
|---|---|
| 日报 KPI 卡 | → ① KPI 条前两格（+ 较昨日） |
| 日报部门卡 | → ④ 部门下钻卡 |
| 日报产量/产值双轴柱图 | → ② 近 30 日趋势图（按部门堆叠） |
| 日报部门汇总表 | → 取消（当日部门数据已在④，月度在③）**⚠ 待确认** |
| 月报 KPI 卡 | → ① KPI 条后两格（本月累计 / 日均，修正 0 值缺陷） |
| 月报月度部门卡 | → ③ 本月部门排行 + ① 本月累计 |
| 月报堆叠趋势图 | → ② 近 30 日趋势图 |
| 月报每日明细表 | → 取消，由②趋势图 + 明细抽屉（按日期范围筛选）+ Excel 导出覆盖 **⚠ 待确认** |

> **⚠ 待确认项**：后两行取消了两个"聚合表"。判断依据是明细抽屉可按日期范围筛选并导出，且 Excel 导出本就含按日数据。**如果这两张表是某些人每天必看的工作面，需要保留**，那应在抽屉内增加一个"按日汇总"视图，而不是恢复 Tab。请评审时明确。

### 4.4 移动端（M2）

- **主屏**（一屏到底，不滚动）：
  - 日期条：`‹ 2026-09-29 › [今天]`
  - Hero：今日产量（大字 + 较昨日）、今日产值（大字 + 较昨日）
  - 一行：本月累计 + 生产天数
  - 三张部门卡（部门名 + 今日件数 + 占比条 + `›`）
  - 底部固定操作条：`[明细] [+ 录入]`
  - **不放趋势图**（D9）。
- **明细页**：全屏列表页（非抽屉），顶部日期条 + 部门筛选 chips，列表项 = 产品 / 部门·时间·录单人 / 数量 / 产值；点击进入编辑，左滑删除；上滑加载更多。
- 点部门卡 → 进入明细页并带上该部门筛选，**与 PC 抽屉同一套筛选语义**。

---

## 5. 权限模型

### 5.1 现状约束（已核实）

- `Permission` 是扁平功能位（`code / name / parent_id / icon / url / section / section_name / sort_order / is_nav`），用户通过多对多关联；**没有数据范围概念**。
- `User` 只有 `factory`（东莞/湖北），**没有 `department` 字段**。
- `daily_production_record` 表无 factory 列，天然范围键只有 `department`。
- `core/deps.py:278` `require_permission(name)` 是布尔检查，单码放行。
- `core/nav_context.py:19` `SPECIAL_PERMISSION_MAP` 支持把一个导航项的 `code` 映射到**多个**权限码（取"任一"），已有 `'outsource_manage': ['outsource_manage', 'outsource_view']` 先例。

### 5.2 权限点设计

新增 6 个码，挂在新/既有「生产报表」父权限下：

```
production_summary_view                  （保留，语义 = 全部门只读，给厂长/老板）
production_summary_manage                （保留，语义 = 全部门可写）
production_summary_view_filling          （新增，充棉部只读）
production_summary_view_handcraft        （新增，手工部只读）
production_summary_view_packaging        （新增，包装部只读）
production_summary_manage_filling        （新增，充棉部可写）
production_summary_manage_handcraft      （新增，手工部可写）
production_summary_manage_packaging      （新增，包装部可写）
```

### 5.3 后端解析规则

在 `core/deps.py` 新增一个解析器（供生产模块各接口复用）：

```python
def resolve_production_dept_scope(user: User) -> set[str] | None:
    """返回用户可见的部门集合；None 表示全部部门（持有聚合码）。"""
```

规则：

1. 持有 `production_summary_view` → 返回 `None`（全部部门）。
2. 否则取用户持有的 `production_summary_view_*` 对应的部门集合。
3. 集合为空 → 403 `权限不足`。

写操作用对称的一个解析器：

```python
def resolve_production_write_scope(user: User) -> set[str] | None:
    """返回用户可写的部门集合；None 表示全部部门（持有聚合 manage 码）。"""
```

规则与读一致（`production_summary_manage` → `None`；否则取 `production_summary_manage_*` 对应部门集合；空集 → 403）。更新/删除时必须校验**记录原部门**的归属（防止越权改别的部门的数据），而不仅是新值。

### 5.4 导航可见性

导航项「生产报表」当前只认 `production_summary_view`，会导致只有部门码的用户看不到入口。在 `core/nav_context.py` 的 `SPECIAL_PERMISSION_MAP` 增加：

```python
'production_summary_view': [
    'production_summary_view',
    'production_summary_view_filling',
    'production_summary_view_handcraft',
    'production_summary_view_packaging',
],
```

（`nav_context.py:127-132` 会自动把自身 code 并入，无需重复。）

### 5.5 权限种子与配置

- 新增 `scripts/init_production_dept_permissions.py`（幂等：按 `code` upsert），插入上述 6 行，`parent_id` 指向「生产报表」父权限，`is_nav=0`（**这些不是导航项**，只是功能位）。
- 用户管理页（`PermissionView` / `useUserManagement`）无需改代码 —— 权限树按 `parent_id` 渲染，新增 6 个子项会自动出现。
- **上线顺序**（关键，见 §9 R2）：先种权限 → 再给用户勾选 → 最后发布后端收窄逻辑。

---

## 6. 后端改动

### 6.1 部门范围收窄（`daily_production.py`）

以下接口全部接入 §5.3 的解析器：

| 接口 | 收窄方式 |
|---|---|
| `GET /records` | 若用户范围非 `None`，强制在查询里 `department IN scope`；如果请求显式传了范围外的 `department`，忽略该参数（不报错，避免前端误传即 403） |
| `GET /daily-summary` | 汇总仅统计范围内部门（`departments` 列表与 `overall_*` 均按范围算） |
| `GET /monthly-summary` | 同上 |
| `GET /trend`（新增） | 同上 |
| `GET /export` | 同上 |
| `POST /records` | 校验 `data.department` ∈ 可写范围 |
| `PUT /records/{id}` | 校验**记录原部门** ∈ 可写范围；且新 `department` 也必须在可写范围内 |
| `DELETE /records/{id}` / 批量删除 | 校验**记录原部门** ∈ 可写范围 |

### 6.2 新增 `GET /daily-production/trend`

用途：近 30 日（可跨月）按日、按部门的数量趋势 —— 现有 `monthly-summary` 只能给单月，跨月无解。

- 参数：`start_date`、`end_date`（均 `YYYY-MM-DD`，`end_date - start_date ≤ 92 天`），可选 `department`。
- 返回：`{"days": [{"date": "2026-09-01", "filling": 820, "handcraft": 560, "packaging": 1400, "total": 2780}, ...], "totals": {...}}`
- 无数据的日期**返回 0 而不是缺行**，让图表 x 轴连续。
- 索引：现有 `idx_dpr_dept_date (department, production_date)` 与 `idx_dpr_date` 已覆盖该查询，无需新索引。

### 6.3 `/records` 增加 `created_by` 筛选

明细抽屉需要"按录单人筛"。加一个可选 `created_by: str = ''` 参数，`create_time` 已有 `created_by` 列（`daily_production_record.created_by`，String(50)）。默认倒序按 `production_date DESC, id DESC`。

### 6.4 月报字段一致性修正

`get_monthly_summary` 已返回 `monthly_total_quantity` / `monthly_total_value`；**修正点在前端**（§4.1）。同时在后端**移除误导**：`MonthlySummaryResponse` 与 `frontend-vite/src/types/index.ts:428-430` 中那两行"历史兼容字段"注释应删除，避免下一个人继续踩。

### 6.5 批量删除

新增 `POST /daily-production/records/batch-delete`，body `{"ids": [int]}`。

**护栏（因为现有删除是物理删除且仅写 logger）**：`daily_production_service.delete_record` 的执行是 `await db.delete(record)` + `logger.info`，**不可恢复、无审计表**（`daily_production_service.py:238-247`）。因此：

1. 单次 `len(ids) ≤ 100`，超出返回 400。
2. 服务端逐条校验部门可写范围，**任一条越权则整批拒绝**（不做部分成功）。
3. 写审计日志：`logger.info` 记录操作人、时间、被删 `id` 列表、每条的产品名/数量/日期 —— 保证可从日志追溯（这是当前唯一可追溯手段）。
4. 前端二次确认弹窗必须显示条数和合计产量，不能只问"确定删除吗"。

> 备注：更彻底的做法是加软删除列（`is_deleted` + 所有查询过滤）。那会触及所有读路径与导出，**本期不做**（§1.4），但建议列入后续技术债。

### 6.6 导出

`GET /export` 已支持 `start_date / end_date / department`，**无需改后端**；前端改为传当前筛选（抽屉的日期范围 + 部门；主屏「导出」默认导当前所选日期的范围）。

---

## 7. 前端改动

### 7.1 硬约束

- **单 `.vue` ≤ 400 行**（项目硬门禁）。
- 沿用既有结构模式：`XxxView.vue` 只做编排（状态 + 查询 + 事件），子组件承载视图。这也是 `material/` 最近一次改版 settle 下来的模式。

### 7.2 PC 文件清单

| 动作 | 文件 | 说明 |
|---|---|---|
| 改造 | `views/production/ProductionView.vue` | 编排层：日期状态、三个 query、抽屉开合 |
| 改造 | `components/CockpitToolbar.vue`（原 `ProductionToolbar.vue`） | 去掉 Tab，加「明细」入口 |
| 新增 | `components/CockpitKpiRow.vue` | ① KPI 条（含较昨日/较上月，昨日为 0 显示 `—`） |
| 新增 | `components/ProductionTrendPanel.vue` | ② 近 30 日堆叠柱 + 合计折线 |
| 新增 | `components/DeptRankPanel.vue` | ③ 本月部门排行 |
| 新增 | `components/DeptDrillCards.vue` | ④ 部门下钻卡（含 0 值/加载态） |
| 新增 | `components/RecordDrawer.vue` | 明细抽屉（筛选 + 表格 + 分页 + 批量） |
| 新增 | `components/RecordEditDialog.vue` | 编辑弹窗，复用录入表单字段 |
| 重命名 | `components/ProductionEntryDrawer.vue` → `ProductionEntryDialog.vue` | 它实际是居中模态，名实不符 |
| 新增 | `composables/useProductionTrend.ts` | 趋势数据 + ECharts（替代 `useProductionCharts.ts` 的日报图部分） |
| 新增 | `composables/useProductionRecords.ts` | 明细查询/筛选/分页/增删改 |
| 删除 | `components/ProductionDailyPanel.vue`、`ProductionMonthlyPanel.vue` | 被 ①②③④ 替代，且消除了约 90 行重复 CSS |
| 删除 | `components/KpiCard.vue` | 改用共享 `UiStatCard.vue` 或统一到 `CockpitKpiRow` |
| 改造 | `composables/useProductionCharts.ts` | 只保留趋势图逻辑（或整体并入 `useProductionTrend.ts` 后删除） |
| 改造 | `api/production.ts` | 接 `records` 全套、`trend`、批量删除 |
| 改造 | `types/index.ts` | 删除 `MonthlySummary` 的历史兼容字段 |

### 7.3 移动端文件清单

| 动作 | 文件 | 说明 |
|---|---|---|
| 重写 | `mobile/views/production/MProductionView.vue` | M2 布局 |
| 新增 | `mobile/views/production/MProductionRecordsView.vue` | 全屏明细列表页 |
| 改造 | `router/index.ts` | 移动端路由注册明细页 |
| 改造 | `api/production.ts` | 与 PC 共用同一套 API 封装 |

### 7.4 视觉与一致性

- 全部色值替换为 `styles/app.css` 的 `--color-primary-*` token；部门色（充棉蓝 / 手工绿 / 包装琥珀）抽为组件级变量，**一处定义、四处引用**。
- 图表配置抽取公共 base option（tooltip/grid/axis 样式）。
- 统一使用项目的 `showToast` / `UiConfirmDialog` / `UiSkeleton` / `UiEmpty`，移除手绘 toast。
- 所有区块补齐**加载骨架**与**空态**（数据薄，空态是常态而非例外）。

---

## 8. 测试策略

### 8.1 后端（`fastapi_app/tests/`）

- `test_daily_production_trend.py`：跨月区间、无数据日期补 0、超 92 天拒绝。
- `test_daily_production_dept_scope.py`：三种用户（仅充棉 / 三部门 / 全部门聚合）对 `records`、`daily-summary`、`monthly-summary`、`trend`、`export` 的可见数据正确；越权部门参数被忽略而非 403。
- `test_daily_production_write_scope.py`：跨部门录入 403；改/删他部门记录 403；改记录时把部门改到范围外 403。
- `test_daily_production_batch_delete.py`：超 100 条拒绝；含越权 id 时整批拒绝且**无任何记录被删**（事务性）；审计日志包含 id 列表。
- `test_daily_production_records_filter.py`：`created_by` 筛选、分页边界（`per_page` 200 上限）。
- `test_daily_production_monthly_fields.py`：断言 `monthly_total_quantity` 与 `daily_data` 合计一致（锁死 D-2 类字段漂移）。

### 8.2 前端（`frontend-vite/src/test/`，vitest）

- KPI 计算：较昨日、较上月、日均；**昨日为 0 时显示 `—` 而非 `Infinity%` 或 `NaN%`**。
- 抽屉筛选 → 请求参数映射；点部门卡后部门筛选被预置。
- 批量删除确认流：未勾选时禁用、确认弹窗显示条数与合计。
- 权限驱动的可见性：只有充棉码的用户看不到手工/包装部门卡与排行项。
- 趋势图在全部为 0 时渲染空态而非空白画布。

### 8.3 手工验证（必做）

- 三个角色账号各登录一次，PC 与移动各看一遍。
- 录入 → 抽屉里查到 → 改 → 删 → 再查，全链路。
- 导出：主屏单日、抽屉按筛选区间，两份 Excel 内容与界面一致。
- 1366×768 与 1920×1080 两种分辨率。

---

## 9. 风险与未决项

### 9.1 风险

| # | 风险 | 应对 |
|---|---|---|
| R1 | **硬删除 + 批量删除**：现有删除是物理删除、仅写 logger、无审计表。批量删除会放大误操作后果 | §6.5 三重护栏（上限 100、整批事务拒绝、审计日志含 id 列表）；软删除列入技术债 |
| R2 | **权限拆分上线顺序**：若后端先上线收窄逻辑，而用户还没勾选部门码，车间用户会直接 403、导航也消失 | 严格按 §5.5 顺序：种权限 → 配用户 → 发后端；上线前用测试账号验证三种角色 |
| R3 | `production_summary.py`（工艺/包装记录）**共用** `production_summary_view/manage` 聚合码，前端已无调用（`productionApi` 全仓零引用） | 不改动该文件的行为；聚合码语义保持"全部门"，因此持有聚合码的用户访问这些接口不受影响 |
| R4 | 数据薄 → 趋势图/较上月大量空态 | 空态显式设计（§7.4）；对比类指标在分母为 0 时显示 `—` |
| R5 | 删除旧面板（`ProductionDailyPanel` / `ProductionMonthlyPanel`）可能带走某些人常用但未言明的视图 | §4.3 待确认项；若需保留，在抽屉内加"按日汇总"视图而非恢复 Tab |
| R6 | 移动端路由与 PC 共用 `/production` 路径，按设备分流；新增明细页需确认分流逻辑与返回栈 | 实现时先验证 `router/index.ts` 的移动端分流与 `MobileNavBar` 返回行为 |

### 9.2 未决项（需评审确认）

1. **§4.3 的两个"聚合表"是否取消**（当日部门汇总表、月报每日明细表）—— 影响是否需要抽屉内的"按日汇总"视图。
2. **批量删除是否值得做** —— 若业务上极少一次删多条，可以只保留单条删除，直接消除 R1。
3. **日均产量的分母** —— 本设计取"生产天数"（有产量的天）。若业务口径是自然日或应扣除休息日，需修正。
4. **"录单人"筛选的价值** —— 取决于 `created_by` 在生产数据里是否都有值（历史数据可能为空）。

---

## 10. 实施顺序（概要）

详细任务拆分交由 `writing-plans` 生成。此处只定阶段顺序，依据是"后端能力 → 权限 → 前端消费"的依赖方向与 §5.5 的上线顺序约束：

1. **后端能力**：`/trend` 新增、`/records` 加 `created_by`、批量删除 + 护栏。此时前端无消费方，可独立测试。
2. **权限**：权限种子脚本 + `SPECIAL_PERMISSION_MAP` + 各接口接入范围解析器。**发布前先种权限并配置用户**。
3. **前端数据层**：`api/production.ts`、`types`、两个 composable。
4. **PC 视图**：KPI 条 → 趋势 → 排行 → 部门卡 → 抽屉 → 编辑弹窗 → 删除旧面板。每步保持页面可用。
5. **移动端**：M2 主屏 → 全屏明细页 → 路由。
6. **收尾**：token 统一、骨架/空态、删旧代码、补测试、手工验证（§8.3）。

> 阶段 1–2（后端 + 权限）与阶段 3–6（前端）之间是**清晰的接缝**：前者可独立测试与发布，后者只消费已定的接口。如果一份计划显得过大，应沿这条缝拆成两份计划（后端与权限一份、前端一份），而不是按前端页面再切。


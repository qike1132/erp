# 生产驾驶舱 · PC 端 实施计划（Plan B1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 PC 端 `/production` 从"日报/月报双 Tab 报表"重构为"一屏固定驾驶舱 + 全功能明细抽屉"，并按设计规格的 V1（清爽蓝白、统一 token）落地视觉。

**Architecture:** 沿用本仓库既有模式：`ProductionView.vue` 只做编排（状态 + 数据查询 + 事件），每个视图区块是一个独立组件，数据逻辑进 composable。**能纯函数化的逻辑一律抽成纯函数**（KPI 环比、筛选→请求参数、ECharts option 构造），因为纯函数可以在 vitest 里直接断言，而挂载组件只能验证渲染。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript、`@tanstack/vue-query`、PrimeVue（经 `src/components/ui/*` 二次封装）、ECharts（经 `src/utils/echartsPreload.ts` 的 `ensureEcharts()` 动态加载）、Tailwind v4（`app.css` 的 token 变量）、vitest + `@vue/test-utils`（jsdom）。

**Spec:** `docs/superpowers/specs/2026-09-29-production-cockpit-design.md`（§4 信息架构、§4.1 KPI 口径表、§4.2 明细抽屉、§4.3 旧面板去向、§7 前端改动、§8.2 前端测试）

**Plan A 已完成**：后端接口与按部门权限已上线（分支 `feat/production-cockpit-backend`，已并入 `main`）。本计划只消费那些接口，**不改后端**。

## Global Constraints

- **单 `.vue` 组件 ≤ 400 行（硬门禁）**。门禁脚本 `scripts/check_vue_component_length.py`，经仓库根 `scripts/quality_gate.py` 的棘轮基线执行；**新文件超 400 行即失败**。子组件拆分是达到这个门禁的手段，不是为了好看。
- **前端三条命令**（在 `frontend-vite/` 下）：
  - `npm run type-check`（`vue-tsc --noEmit`）
  - `npm run lint`（`eslint src/ --ext .ts,.vue`）
  - `npm test`（`vitest run`）
  另在**仓库根**跑 `python scripts/quality_gate.py`（同时覆盖后端函数 80 行门禁与 Vue 400 行门禁）。
- **`get<T>()` 不拆 `{ data }`**：`src/api/request.ts` 的 `get` 返回**整个 HTTP 响应体**。所以 `/records` 的响应类型是 `{ success, data: DailyProductionRecord[], total, page, per_page, pages, stats }`（`data` 是顶层字段，不是包装层）。
- **`meta: { hideHeader: true }` 的含义**：`DefaultLayout.vue` 会给 `.content-container` 加 `no-padding`（`padding: 0; overflow: visible`），**布局不再提供内边距与滚动容器** —— 视图必须自己渲染容器（用 `app.css` 里已有的全局类 `page-card` / `page-card-main` / `page-card-body`）。
- **统一 token**：颜色一律用 `app.css` 的变量（`--color-primary-*` 等）或 Tailwind 的语义类（`text-heading` / `text-text-secondary` / `bg-surface-card` / `border-border-light`）。**不得**再写死 `#eff6ff` / `#1e40af` 这类字面量 —— 现存页面里那批硬编码色值正是本次要清掉的。
- 部门键固定为 `filling` / `handcraft` / `packaging`；中文名 充棉部 / 手工部 / 包装部。**部门色一处定义**（`useProductionCharts.ts` 现有的 `deptColors` 提为共享常量），四处引用，不得各写一份。
- 权限：后端已按部门收窄。前端**不需要**按部门隐藏 UI —— 后端返回的 `departments` / `monthly_departments` / `trend.departments` 只含可见部门，界面按返回内容渲染即可。**不要**在前端硬编码三个部门去渲染（否则受限用户会看到空卡片）。
- 测试文件放 `src/test/`，命名 `<被测组件或模块>.<关注点>.test.ts`；用 `mount`（不用 `shallowMount`）；`FontAwesomeIcon` 已由 `src/test/setup.ts` 全局 stub，不要在测试里再 stub 它。
- **工作区是脏的**：有 30+ 个其它会话的未提交改动，且其它会话也在向分支提交。提交时**只用显式路径** `git add <path>`，**绝不** `git add -A` / `git add .` / `git commit -a`，**绝不** stash / revert / clean。本机 bash 有 `_lc` 别名故障，`git`/`cat`/`head` 等命令要加 `command` 前缀。
- 提交信息以 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` 结尾。

## Review Focus

以下 5 类输入是规格隐含、但"渲染出来看着对"最容易掩盖错误的（按可能性排序）。每一行都在其归属任务里配了测试：

1. **`stats` 为 `null` 或全 0**（筛选条件下没有任何记录）→ 抽屉底部的合计不能显示 `NaN` 或空白，要显示 `0`。→ Task 8
2. **昨日的产量/产值为 0**（昨天没生产，或刚上线没数据）→ "较昨日"必须显示 `—`，**不得**显示 `Infinity%` 或 `NaN%`。→ Task 3
3. **近 30 日全部为 0**（新上线、或该用户范围内没数据）→ 趋势图必须渲染**空态**，不能是一块空白画布或一条贴底的 0 线。→ Task 4
4. **`trend.departments` 少于三个**（受限用户只可见一个部门）→ 图表与排行只画返回的那些部门，不得画三条（其中两条恒为 0）。→ Task 2 / Task 5
5. **抽屉里的筛选条件组合**（"本周"跨月、自定义区间跨月、部门为空、录单人留空）→ 生成的请求参数必须是区间优先、空值省略，不能把 `created_by=''` 传给后端。→ Task 7

---

### Task 1: 数据层 —— 类型与 API

**Files:**
- Modify: `frontend-vite/src/types/index.ts`（新增 3 个接口，删除 2 个过时字段）
- Modify: `frontend-vite/src/api/production.ts`（`dailyProductionApi` 加 `trend`、`records` 改类型化）
- Test: `frontend-vite/src/test/productionApi.params.test.ts`

**Interfaces:**
- Consumes: 后端 `GET /api/v1/daily-production/records`、`GET /api/v1/daily-production/trend`（Plan A 已实现）
- Produces:
  - `ProductionRecordStats`、`ProductionRecordListResponse`、`TrendDay`、`TrendResponse`、`RecordsQuery`（类型）
  - `dailyProductionApi.records(params: RecordsQuery) => Promise<ProductionRecordListResponse>`
  - `dailyProductionApi.trend(params: { start_date: string; end_date: string; department?: string }) => Promise<TrendResponse>`

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/productionApi.params.test.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'

const getMock = vi.fn()

vi.mock('@/api/request', () => ({
  get: (...args: unknown[]) => getMock(...args),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  download: vi.fn(),
}))

import { dailyProductionApi } from '@/api/production'

describe('dailyProductionApi.records', () => {
  beforeEach(() => {
    getMock.mockReset()
    getMock.mockResolvedValue({ success: true, data: [], total: 0, page: 1, per_page: 50, pages: 0, stats: null })
  })

  it('按年月筛选时只传 year/month', async () => {
    await dailyProductionApi.records({ year: 2026, month: 9, page: 1, per_page: 50 })

    expect(getMock).toHaveBeenCalledWith('/daily-production/records', {
      year: 2026,
      month: 9,
      page: 1,
      per_page: 50,
    })
  })

  it('按区间筛选时传 start_date/end_date 且不带 year/month', async () => {
    await dailyProductionApi.records({ start_date: '2026-08-25', end_date: '2026-09-02' })

    const params = getMock.mock.calls[0]![1] as Record<string, unknown>
    expect(params).toEqual({ start_date: '2026-08-25', end_date: '2026-09-02' })
    expect(params).not.toHaveProperty('year')
    expect(params).not.toHaveProperty('month')
  })

  it('参数原样透传，不在 API 层补默认值', async () => {
    // 默认值由调用方（useProductionRecords）决定；API 层补默认值会让"区间"筛选被
    // 悄悄带上 year/month，后端虽有"区间优先"规则，但前端不该依赖它兜底。
    await dailyProductionApi.records({ created_by: '张三' })

    expect(getMock).toHaveBeenCalledWith('/daily-production/records', { created_by: '张三' })
  })
})

describe('dailyProductionApi.trend', () => {
  beforeEach(() => {
    getMock.mockReset()
    getMock.mockResolvedValue({
      success: true, start_date: '2026-09-01', end_date: '2026-09-02',
      departments: ['filling', 'handcraft', 'packaging'], days: [],
    })
  })

  it('传区间与可选部门', async () => {
    await dailyProductionApi.trend({ start_date: '2026-09-01', end_date: '2026-09-30', department: 'filling' })

    expect(getMock).toHaveBeenCalledWith('/daily-production/trend', {
      start_date: '2026-09-01',
      end_date: '2026-09-30',
      department: 'filling',
    })
  })

  it('不传部门时参数里没有 department 键', async () => {
    await dailyProductionApi.trend({ start_date: '2026-09-01', end_date: '2026-09-30' })

    expect(getMock.mock.calls[0]![1]).toEqual({ start_date: '2026-09-01', end_date: '2026-09-30' })
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/productionApi.params.test.ts`
Expected: FAIL —— `dailyProductionApi.trend is not a function`（以及 `records` 当前会补 year/month 默认值，前两个用例也会红）

- [ ] **Step 3: 加类型**

在 `frontend-vite/src/types/index.ts` 中：

a) 在 `DailyProductionRecord` 之后新增：

```ts
export interface ProductionRecordStats {
  total_quantity: number
  total_value: number
  total_sku: number
}

/** GET /daily-production/records 的响应体（`get<T>` 不拆 { data }，data 是顶层字段） */
export interface ProductionRecordListResponse {
  success: boolean
  data: DailyProductionRecord[]
  total: number
  page: number
  per_page: number
  pages: number
  stats: ProductionRecordStats | null
}

/** 明细抽屉的查询参数。year/month 与 start_date/end_date 二选一，区间优先。 */
export interface RecordsQuery {
  year?: number
  month?: number
  start_date?: string
  end_date?: string
  department?: string
  created_by?: string
  /** 产品名或 69 码关键词（Task 7 给后端加的筛选参数） */
  keyword?: string
  sort?: 'asc' | 'desc'
  page?: number
  per_page?: number
  production_date?: string
}

export interface TrendDay {
  date: string
  filling: number
  handcraft: number
  packaging: number
  total: number
}

/** GET /daily-production/trend 的响应体。departments 只含当前用户可见部门。 */
export interface TrendResponse {
  success: boolean
  start_date: string
  end_date: string
  departments: string[]
  days: TrendDay[]
}
```

b) 从 `MonthlySummary` 中**删除**这两行及其注释（规格 §6.4 的前端一半：后端只返回 `monthly_total_*`，这两行"历史兼容字段"注释正是当年掩盖"月报 KPI 恒为 0"的东西）：

```ts
  /** 历史兼容字段：后端实际不返回（月报面板模板仍按可选字段访问，undefined 时由 ?? 0 兜底） */
  overall_quantity?: number
  overall_value?: number
```

- [ ] **Step 4: 改 API**

把 `frontend-vite/src/api/production.ts` 中的 `dailyProductionApi` 替换为：

```ts
export const dailyProductionApi = {
  /**
   * 明细列表。参数由调用方决定：传 year/month 或传 start_date/end_date（区间优先）。
   * 本层**不补默认值** —— 补了会让"区间"筛选被悄悄带上 year/month。
   */
  records: (params: RecordsQuery) =>
    get<ProductionRecordListResponse>('/daily-production/records', params),
  createRecord: (data: Record<string, unknown>) => post('/daily-production/records', data),
  updateRecord: (id: number, data: Record<string, unknown>) => put(`/daily-production/records/${id}`, data),
  deleteRecord: (id: number) => del(`/daily-production/records/${id}`),
  dailySummary: (date: string) => get<DailySummary>('/daily-production/daily-summary', { date }),
  monthlySummary: (params?: QueryParams) =>
    get<MonthlySummary>('/daily-production/monthly-summary', {
      year: new Date().getFullYear(),
      month: new Date().getMonth() + 1,
      ...params,
    }),
  /** 近 N 日按部门数量趋势（可跨月，后端上限 92 天） */
  trend: (params: { start_date: string; end_date: string; department?: string }) =>
    get<TrendResponse>('/daily-production/trend', params),
  export: (params?: QueryParams) => download('/daily-production/export', 'production_report.xlsx', params),
  productInfo: (productId: number) =>
    get<{ success: boolean; data: { id: number; name: string; barcode: string; price: number } }>(
      `/daily-production/product-info/${productId}`,
    ),
}
```

并把文件头部的 import 行补上新类型：

```ts
import type {
  DailySummary,
  MonthlySummary,
  ProductionCraft,
  ProductionRecordListResponse,
  QueryParams,
  RecordsQuery,
  TrendResponse,
} from '@/types'
```

`productionApi`（工艺那部分）**保持原样不动**。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/productionApi.params.test.ts`
Expected: PASS（5 passed）

- [ ] **Step 6: 类型检查**

Run: `cd frontend-vite && npm run type-check`
Expected: 无错误。**注意**：本步会因为 Task 10 之前旧的 `ProductionMonthlyPanel.vue` 仍在引用 `overall_quantity` 而报错 —— 如果出现该错误，说明删除类型字段的影响面需要在本任务内处理：把 `ProductionMonthlyPanel.vue` 里对 `monthlySummary.overall_quantity` / `overall_value` 的引用改为 `monthly_total_quantity` / `monthly_total_value`（该文件将在 Task 10 删除，此处只是让它先编译通过）。

- [ ] **Step 7: 提交**

```bash
git add frontend-vite/src/types/index.ts frontend-vite/src/api/production.ts frontend-vite/src/test/productionApi.params.test.ts frontend-vite/src/views/production/components/ProductionMonthlyPanel.vue
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息写入临时文件，内容：

```
feat(production): 前端数据层补 trend/records 类型与 API

新增 ProductionRecordListResponse / TrendResponse / RecordsQuery；
records 改为类型化且不再补 year/month 默认值（由调用方决定区间或月份）；
删除 MonthlySummary 的 overall_* 历史兼容字段（规格 §6.4 的前端一半）。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 2: 趋势图 option 构造（纯函数）

**Files:**
- Create: `frontend-vite/src/views/production/composables/trendChartOption.ts`
- Test: `frontend-vite/src/test/productionTrendOption.test.ts`

**Interfaces:**
- Consumes: `TrendDay`、`TrendResponse`（Task 1）
- Produces:
  - `DEPT_LABELS: Record<string, string>`（`filling` → 充棉部 …）—— 本文件是部门中文名的**唯一来源**，后续 Task 3/5/6 都从这里 import
  - `DEPT_COLORS: Record<string, string>`（`filling` → `#3b82f6`、`handcraft` → `#22c55e`、`packaging` → `#f59e0b`）—— 部门色的唯一来源
  - `buildTrendOption(days: TrendDay[], departments: string[]) => Record<string, unknown>`

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/productionTrendOption.test.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { DEPT_COLORS, DEPT_LABELS, buildTrendOption } from '@/views/production/composables/trendChartOption'
import type { TrendDay } from '@/types'

function day(date: string, filling: number, handcraft: number, packaging: number): TrendDay {
  return { date, filling, handcraft, packaging, total: filling + handcraft + packaging }
}

describe('buildTrendOption', () => {
  it('为每个可见部门生成一条堆叠柱系列，顺序与传入的 departments 一致', () => {
    const days = [day('2026-09-01', 1, 2, 3), day('2026-09-02', 4, 5, 6)]

    const option = buildTrendOption(days, ['filling', 'handcraft', 'packaging'])
    const series = option.series as Array<Record<string, unknown>>

    expect(series).toHaveLength(3)
    expect(series.map((s) => s.name)).toEqual(['充棉部', '手工部', '包装部'])
    expect(series.every((s) => s.type === 'bar' && s.stack === 'dept')).toBe(true)
  })

  it('受限用户只可见一个部门时只画一条系列，不画三条', () => {
    // Review Focus #4：trend.departments 可能少于三个
    const days = [day('2026-09-01', 7, 0, 0)]

    const option = buildTrendOption(days, ['filling'])
    const series = option.series as Array<Record<string, unknown>>

    expect(series).toHaveLength(1)
    expect(series[0]!.name).toBe('充棉部')
    expect(series[0]!.data).toEqual([7])
  })

  it('x 轴用日期后两位，逐日连续', () => {
    const days = [day('2026-09-01', 1, 0, 0), day('2026-09-02', 0, 0, 0), day('2026-09-03', 5, 0, 0)]

    const option = buildTrendOption(days, ['filling', 'handcraft', 'packaging'])
    const xAxis = option.xAxis as Record<string, unknown>

    expect(xAxis.data).toEqual(['01', '02', '03'])
    expect((option.series as Array<Record<string, unknown>>)[0]!.data).toEqual([1, 0, 5])
  })

  it('合计折线始终是第四条系列，取每天的 total', () => {
    const days = [day('2026-09-01', 1, 2, 3)]

    const option = buildTrendOption(days, ['filling', 'handcraft', 'packaging'])
    const series = option.series as Array<Record<string, unknown>>
    const totalSeries = series[series.length - 1]!

    expect(totalSeries.name).toBe('合计')
    expect(totalSeries.type).toBe('line')
    expect(totalSeries.data).toEqual([6])
  })

  it('部门色与中文名来自共享常量', () => {
    expect(DEPT_LABELS.filling).toBe('充棉部')
    expect(DEPT_COLORS.packaging).toBe('#f59e0b')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/productionTrendOption.test.ts`
Expected: FAIL —— `Failed to resolve import "@/views/production/composables/trendChartOption"`

- [ ] **Step 3: 写实现**

创建 `frontend-vite/src/views/production/composables/trendChartOption.ts`：

```ts
/**
 * 趋势图 ECharts option 构造 —— 纯函数，不依赖 ECharts 运行时。
 *
 * 刻意不用 echarts.graphic.LinearGradient 做渐变：那会把 option 构造绑死在
 * 动态 import 的 ECharts 模块上，令本文件无法作为纯函数单测。堆叠柱用平色即可。
 *
 * 同时是部门中文名与部门色的**唯一来源**：其它组件一律从这里 import，
 * 不得各写一份（原 useProductionCharts.ts 与本文件曾各持一份部门色）。
 */
import type { TrendDay } from '@/types'

export const DEPT_LABELS: Record<string, string> = {
  filling: '充棉部',
  handcraft: '手工部',
  packaging: '包装部',
}

export const DEPT_COLORS: Record<string, string> = {
  filling: '#3b82f6',
  handcraft: '#22c55e',
  packaging: '#f59e0b',
}

const TOTAL_COLOR = '#64748b'

export function buildTrendOption(
  days: TrendDay[],
  departments: string[],
): Record<string, unknown> {
  const series = departments.map((dept) => ({
    name: DEPT_LABELS[dept] ?? dept,
    type: 'bar',
    stack: 'dept',
    barMaxWidth: 18,
    itemStyle: { color: DEPT_COLORS[dept] ?? TOTAL_COLOR },
    data: days.map((d) => (d as unknown as Record<string, number>)[dept] ?? 0),
  }))

  series.push({
    name: '合计',
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 6,
    lineStyle: { width: 2, color: TOTAL_COLOR },
    itemStyle: { color: TOTAL_COLOR },
    data: days.map((d) => d.total),
  } as never)

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e2e8f0',
      textStyle: { color: '#1e293b', fontSize: 13 },
    },
    legend: {
      bottom: 0,
      itemWidth: 12,
      itemHeight: 12,
      textStyle: { fontSize: 12, color: '#475569' },
    },
    grid: { left: 56, right: 20, top: 20, bottom: 44 },
    xAxis: {
      type: 'category',
      data: days.map((d) => d.date.slice(-2)),
      axisLabel: { fontSize: 11, color: '#94a3b8' },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: '产量',
      axisLabel: { fontSize: 11, color: '#94a3b8' },
      splitLine: { lineStyle: { color: '#f1f5f9', type: 'dashed' } },
    },
    series,
  }
}
```

**注意**：`series` 数组先用 `departments.map(...)` 得到柱系列，再 `push` 合计折线 —— 上面两处的类型断言（`as never` / `as unknown as Record<string, number>`）是为了让混合了 bar 与 line 的数组通过 `vue-tsc`。如果 `npm run type-check` 对这两处不满意，改为先声明 `const series: Record<string, unknown>[] = [...]` 再 push，不要用 `any`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/productionTrendOption.test.ts`
Expected: PASS（5 passed）

- [ ] **Step 5: lint + type-check + 提交**

Run: `cd frontend-vite && npm run lint && npm run type-check`
Expected: 均无错误

```bash
git add frontend-vite/src/views/production/composables/trendChartOption.ts frontend-vite/src/test/productionTrendOption.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): 新增趋势图 option 纯函数构造

部门中文名与部门色的唯一来源；受限用户只画可见部门，合计折线固定最后一条。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 3: KPI 环比（纯函数）+ KPI 条组件

**Files:**
- Create: `frontend-vite/src/views/production/composables/kpiDelta.ts`
- Create: `frontend-vite/src/views/production/components/CockpitKpiRow.vue`
- Test: `frontend-vite/src/test/productionKpiDelta.test.ts`
- Test: `frontend-vite/src/test/cockpitKpiRow.render.test.ts`

**Interfaces:**
- Consumes: `UiStatCard`（`accent` prop + `label`/`default`/`extra`/`icon` slots）
- Produces:
  - `formatDelta(current: number, previous: number) => { text: string; tone: 'up' | 'down' | 'flat' }`
  - `CockpitKpiRow` 组件 props：`{ today: DailySummary | null; yesterday: DailySummary | null; monthly: MonthlySummary | null }`

- [ ] **Step 1: 写失败的测试（环比纯函数）**

创建 `frontend-vite/src/test/productionKpiDelta.test.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { formatDelta } from '@/views/production/composables/kpiDelta'

describe('formatDelta', () => {
  it('增长显示 +x.x% 且为 up', () => {
    expect(formatDelta(112, 100)).toEqual({ text: '+12.0%', tone: 'up' })
  })

  it('下降显示 -x.x% 且为 down', () => {
    expect(formatDelta(90, 100)).toEqual({ text: '-10.0%', tone: 'down' })
  })

  it('持平显示 0.0% 且为 flat', () => {
    expect(formatDelta(100, 100)).toEqual({ text: '0.0%', tone: 'flat' })
  })

  it('分母为 0 时显示破折号，绝不出现 Infinity 或 NaN', () => {
    // Review Focus #2：昨天没生产、或刚上线没数据时，分母就是 0
    expect(formatDelta(50, 0)).toEqual({ text: '—', tone: 'flat' })
    expect(formatDelta(0, 0)).toEqual({ text: '—', tone: 'flat' })
  })

  it('分子为 0 而分母非 0 时是 -100%', () => {
    expect(formatDelta(0, 80)).toEqual({ text: '-100.0%', tone: 'down' })
  })

  it('非有限数值一律退化为破折号', () => {
    expect(formatDelta(Number.NaN, 100)).toEqual({ text: '—', tone: 'flat' })
    expect(formatDelta(100, Number.NaN)).toEqual({ text: '—', tone: 'flat' })
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/productionKpiDelta.test.ts`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 写环比实现**

创建 `frontend-vite/src/views/production/composables/kpiDelta.ts`：

```ts
/**
 * KPI 环比文案。
 *
 * 分母为 0（昨天没生产 / 刚上线无数据）时返回破折号 —— 这是刻意的：
 * 直接算会得到 Infinity% 或 NaN%，显示在界面上比"没有对比"更糟。
 */
export interface DeltaText {
  text: string
  tone: 'up' | 'down' | 'flat'
}

export function formatDelta(current: number, previous: number): DeltaText {
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) {
    return { text: '—', tone: 'flat' }
  }
  const pct = ((current - previous) / previous) * 100
  if (Math.abs(pct) < 0.05) return { text: '0.0%', tone: 'flat' }
  const sign = pct > 0 ? '+' : '-'
  return { text: `${sign}${Math.abs(pct).toFixed(1)}%`, tone: pct > 0 ? 'up' : 'down' }
}

/** 生产天数：当月有产量的天数（后端 daily_data 逐日给出，含 0 的天） */
export function countProductionDays(days: Array<{ total: { quantity: number } }> | undefined): number {
  if (!days?.length) return 0
  return days.filter((d) => d.total.quantity > 0).length
}

/** 日均产量 = 当月累计 ÷ 生产天数；生产天数为 0 时返回 0（不是 NaN） */
export function dailyAverage(totalQuantity: number, productionDays: number): number {
  if (!productionDays) return 0
  return totalQuantity / productionDays
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/productionKpiDelta.test.ts`
Expected: PASS（6 passed）

- [ ] **Step 5: 写失败的测试（KPI 条组件）**

创建 `frontend-vite/src/test/cockpitKpiRow.render.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import CockpitKpiRow from '@/views/production/components/CockpitKpiRow.vue'
import type { DailySummary, MonthlySummary } from '@/types'

function daily(quantity: number, value: number): DailySummary {
  return {
    date: '2026-09-29',
    departments: [],
    overall_quantity: quantity,
    overall_value: value,
    overall_sku_count: 3,
  }
}

const monthly: MonthlySummary = {
  year: 2026,
  month: 9,
  daily_data: [
    {
      date: '2026-09-01', day: 1,
      filling: { quantity: 10, value: 70, sku_count: 1 },
      handcraft: { quantity: 0, value: 0, sku_count: 0 },
      packaging: { quantity: 0, value: 0, sku_count: 0 },
      total: { quantity: 10, value: 70, sku_count: 1 },
    },
  ],
  monthly_departments: [],
  monthly_total_quantity: 10,
  monthly_total_value: 70,
}

describe('CockpitKpiRow', () => {
  it('渲染四个 KPI：今日产量/今日产值/本月累计/日均产量', () => {
    const wrapper = mount(CockpitKpiRow, {
      props: { today: daily(4250, 27170), yesterday: daily(3780, 25130), monthly, previousMonth: null },
    })

    const text = wrapper.text()
    expect(text).toContain('今日产量')
    expect(text).toContain('今日产值')
    expect(text).toContain('本月累计')
    expect(text).toContain('日均产量')
    expect(text).toContain('4,250')
  })

  it('昨日为 0 时较昨日显示破折号', () => {
    // Review Focus #2 的渲染侧断言：纯函数已测，这里确认界面真的用了它
    const wrapper = mount(CockpitKpiRow, {
      props: { today: daily(100, 700), yesterday: daily(0, 0), monthly, previousMonth: null },
    })

    expect(wrapper.text()).toContain('—')
    expect(wrapper.text()).not.toContain('Infinity')
    expect(wrapper.text()).not.toContain('NaN')
  })

  it('数据未加载时显示骨架而不显示 0', () => {
    const wrapper = mount(CockpitKpiRow, {
      props: { today: null, yesterday: null, monthly: null, previousMonth: null },
    })

    expect(wrapper.find('[data-test="kpi-skeleton"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('0 件')
  })

  it('本月无生产日时日均显示 0 而非 NaN', () => {
    const emptyMonth: MonthlySummary = {
      ...monthly,
      daily_data: [],
      monthly_total_quantity: 0,
      monthly_total_value: 0,
    }
    const wrapper = mount(CockpitKpiRow, {
      props: { today: daily(0, 0), yesterday: daily(0, 0), monthly: emptyMonth, previousMonth: null },
    })

    expect(wrapper.text()).not.toContain('NaN')
  })

  it('上月无生产日时"较上月"显示破折号', () => {
    // 规格 §4.1 的日均口径含"较上月"；上月无数据时同样是分母为 0 的情形
    const wrapper = mount(CockpitKpiRow, {
      props: { today: daily(100, 700), yesterday: daily(100, 700), monthly, previousMonth: null },
    })

    expect(wrapper.text()).toContain('较上月 —')
  })
})
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/cockpitKpiRow.render.test.ts`
Expected: FAIL —— 组件不存在

- [ ] **Step 7: 写组件**

创建 `frontend-vite/src/views/production/components/CockpitKpiRow.vue`：

```vue
<template>
  <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
    <template v-if="today && monthly">
      <UiStatCard accent="blue">
        <template #label>今日产量</template>
        <template #default>
          {{ formatNumber(today.overall_quantity) }}<small class="ml-1 text-xs font-semibold text-text-muted">件</small>
        </template>
        <template #extra>
          <span :class="deltaClass(quantityDelta.tone)">较昨日 {{ quantityDelta.text }}</span>
        </template>
      </UiStatCard>

      <UiStatCard accent="green">
        <template #label>今日产值</template>
        <template #default>{{ formatCurrency(today.overall_value) }}</template>
        <template #extra>
          <span :class="deltaClass(valueDelta.tone)">较昨日 {{ valueDelta.text }}</span>
        </template>
      </UiStatCard>

      <UiStatCard accent="amber">
        <template #label>本月累计</template>
        <template #default>
          {{ formatNumber(monthly.monthly_total_quantity) }}<small class="ml-1 text-xs font-semibold text-text-muted">件</small>
        </template>
        <template #extra>{{ productionDays }} 个生产日</template>
      </UiStatCard>

      <UiStatCard accent="ocean">
        <template #label>日均产量</template>
        <template #default>
          {{ formatNumber(Math.round(average)) }}<small class="ml-1 text-xs font-semibold text-text-muted">件</small>
        </template>
        <template #extra>
          <span :class="deltaClass(averageDelta.tone)">较上月 {{ averageDelta.text }}</span>
        </template>
      </UiStatCard>
    </template>

    <UiSkeleton v-else data-test="kpi-skeleton" variant="stat" class="col-span-2 lg:col-span-4" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import UiStatCard from '@/components/ui/UiStatCard.vue'
import { formatCurrency, formatNumber } from '@/utils/format'
import type { DailySummary, MonthlySummary } from '@/types'
import { countProductionDays, dailyAverage, formatDelta } from '../composables/kpiDelta'

const props = defineProps<{
  today: DailySummary | null
  yesterday: DailySummary | null
  monthly: MonthlySummary | null
  /** 上月汇总，只用于算"日均较上月"；为 null 时该处显示破折号 */
  previousMonth: MonthlySummary | null
}>()

const quantityDelta = computed(() =>
  formatDelta(props.today?.overall_quantity ?? 0, props.yesterday?.overall_quantity ?? 0),
)
const valueDelta = computed(() =>
  formatDelta(props.today?.overall_value ?? 0, props.yesterday?.overall_value ?? 0),
)

const productionDays = computed(() => countProductionDays(props.monthly?.daily_data))
const average = computed(() =>
  dailyAverage(props.monthly?.monthly_total_quantity ?? 0, productionDays.value),
)

/** 日均较上月：两边都按"当月累计 ÷ 生产天数"算，量纲一致 */
const averageDelta = computed(() => {
  const prevDays = countProductionDays(props.previousMonth?.daily_data)
  if (!prevDays) return formatDelta(0, 0)
  const prevAverage = dailyAverage(props.previousMonth?.monthly_total_quantity ?? 0, prevDays)
  return formatDelta(average.value, prevAverage)
})

function deltaClass(tone: 'up' | 'down' | 'flat'): string {
  if (tone === 'up') return 'text-success-600'
  if (tone === 'down') return 'text-danger-600'
  return 'text-text-muted'
}
</script>
```

**实现时先确认** `src/utils/format.ts` 确实导出 `formatCurrency` 与 `formatNumber`（原 `ProductionView.vue` 就在用这两个），并确认 Tailwind 的 `text-success-600` / `text-danger-600` / `text-text-muted` 类在本仓库可用（`UiStatCard.vue` 用了 `text-text-muted` 与 `border-l-success-500`，所以这些语义色存在）。若 `text-success-600` 不存在，改用 `text-success-500`。

- [ ] **Step 8: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/cockpitKpiRow.render.test.ts src/test/productionKpiDelta.test.ts`
Expected: PASS（11 passed）

- [ ] **Step 9: lint + type-check + 提交**

Run: `cd frontend-vite && npm run lint && npm run type-check`
Expected: 均无错误

```bash
git add frontend-vite/src/views/production/composables/kpiDelta.ts frontend-vite/src/views/production/components/CockpitKpiRow.vue frontend-vite/src/test/productionKpiDelta.test.ts frontend-vite/src/test/cockpitKpiRow.render.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): 新增 KPI 环比纯函数与驾驶舱 KPI 条

分母为 0 时显示破折号而非 Infinity%/NaN%；数据未加载显示骨架。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 4: 趋势面板组件

**Files:**
- Create: `frontend-vite/src/views/production/composables/productionDate.ts`
- Create: `frontend-vite/src/views/production/composables/useProductionTrend.ts`
- Create: `frontend-vite/src/views/production/components/ProductionTrendPanel.vue`
- Test: `frontend-vite/src/test/productionTrendPanel.render.test.ts`

**Interfaces:**
- Consumes: `buildTrendOption`、`DEPT_LABELS`（Task 2）；`ensureEcharts`（`@/utils/echartsPreload`）；`dailyProductionApi.trend`（Task 1）
- Produces:
  - `toLocalDate(d: Date) => string`、`trendRange(days: number, today?: Date) => { start_date: string; end_date: string }`、`mondayOf(d: Date) => Date`（**Task 8 与 Task 11 都要用，不要另写一份**）
  - `useProductionTrend(days: Ref<number>)` → `{ trendQuery }`，其中 `trendQuery` 是 vue-query 的 `useQuery` 结果，`data` 为 `TrendResponse | undefined`
  - `ProductionTrendPanel` 组件 props：`{ trend: TrendResponse | null; loading: boolean }`

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/productionTrendPanel.render.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import ProductionTrendPanel from '@/views/production/components/ProductionTrendPanel.vue'
import type { TrendResponse } from '@/types'

function trend(days: TrendResponse['days'], departments = ['filling', 'handcraft', 'packaging']): TrendResponse {
  return { success: true, start_date: '2026-09-01', end_date: '2026-09-30', departments, days }
}

describe('ProductionTrendPanel', () => {
  it('全部为 0 时渲染空态而不是空白画布', () => {
    // Review Focus #3：新上线或该用户范围内无数据时，30 天全是 0
    const zeroDays = Array.from({ length: 30 }, (_, i) => ({
      date: `2026-09-${String(i + 1).padStart(2, '0')}`,
      filling: 0, handcraft: 0, packaging: 0, total: 0,
    }))

    const wrapper = mount(ProductionTrendPanel, { props: { trend: trend(zeroDays), loading: false } })

    expect(wrapper.find('[data-test="trend-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="trend-chart"]').exists()).toBe(false)
  })

  it('有数据时渲染图表容器', () => {
    const days = [{ date: '2026-09-01', filling: 5, handcraft: 0, packaging: 0, total: 5 }]

    const wrapper = mount(ProductionTrendPanel, { props: { trend: trend(days), loading: false } })

    expect(wrapper.find('[data-test="trend-chart"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="trend-empty"]').exists()).toBe(false)
  })

  it('加载中显示骨架', () => {
    const wrapper = mount(ProductionTrendPanel, { props: { trend: null, loading: true } })

    expect(wrapper.find('[data-test="trend-skeleton"]').exists()).toBe(true)
  })

  it('trend 为 null 且不在加载中时渲染空态', () => {
    const wrapper = mount(ProductionTrendPanel, { props: { trend: null, loading: false } })

    expect(wrapper.find('[data-test="trend-empty"]').exists()).toBe(true)
  })

  it('面板标题写明统计区间', () => {
    const days = [{ date: '2026-09-01', filling: 5, handcraft: 0, packaging: 0, total: 5 }]
    const wrapper = mount(ProductionTrendPanel, { props: { trend: trend(days), loading: false } })

    expect(wrapper.text()).toContain('2026-09-01')
    expect(wrapper.text()).toContain('2026-09-30')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/productionTrendPanel.render.test.ts`
Expected: FAIL —— 组件不存在

- [ ] **Step 3: 写日期工具与 composable**

创建 `frontend-vite/src/views/production/composables/productionDate.ts`：

```ts
/**
 * 生产页共用的日期工具。
 *
 * 刻意单独成文件：趋势区间与明细筛选都要用"本地日期字符串"与"本周一"，
 * 两处各写一份必然漂移 —— 尤其"本地日期"这条：用 toISOString 会按 UTC 切日，
 * 东八区晚上 8 点之后会算成前一天。
 */
/** 本地日期字符串（不要用 toISOString） */
export function toLocalDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 近 N 日区间：今天往前推 N-1 天到今天（闭区间，天然可跨月） */
export function trendRange(days: number, today = new Date()): { start_date: string; end_date: string } {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  const start = new Date(end)
  start.setDate(start.getDate() - (days - 1))
  return { start_date: toLocalDate(start), end_date: toLocalDate(end) }
}

/** 本周一（以周一为一周之始） */
export function mondayOf(d: Date): Date {
  const day = d.getDay() // 0=周日
  const diff = day === 0 ? 6 : day - 1
  const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  monday.setDate(monday.getDate() - diff)
  return monday
}
```

再创建 `frontend-vite/src/views/production/composables/useProductionTrend.ts`：

```ts
/**
 * 近 N 日趋势数据。区间按「今天往前推 N-1 天」到「今天」计算，
 * 因此天然可跨月 —— 这正是新增 /trend 接口的原因（monthly-summary 只服务单月）。
 */
import { computed, type Ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { dailyProductionApi } from '@/api/production'
import { trendRange } from './productionDate'

export function useProductionTrend(days: Ref<number>) {
  const range = computed(() => trendRange(days.value))

  const trendQuery = useQuery({
    queryKey: computed(() => ['daily-production-trend', range.value.start_date, range.value.end_date]),
    queryFn: () => dailyProductionApi.trend(range.value),
    staleTime: 60_000,
  })

  return { trendQuery }
}
```

- [ ] **Step 4: 写组件**

创建 `frontend-vite/src/views/production/components/ProductionTrendPanel.vue`：

```vue
<template>
  <section class="page-card flex min-h-0 flex-col overflow-hidden">
    <header class="page-card-header">
      <span class="text-sm font-bold text-heading">
        <FontAwesomeIcon icon="chart-column" class="mr-1.5 text-primary-500" aria-hidden="true" />
        近 {{ DAYS }} 日产量
      </span>
      <span v-if="trend" class="text-xs font-medium text-text-muted">
        {{ trend.start_date }} ~ {{ trend.end_date }} · 按部门堆叠
      </span>
    </header>

    <div class="page-card-body">
      <UiSkeleton v-if="loading" data-test="trend-skeleton" variant="card" />

      <UiEmpty
        v-else-if="!hasData"
        data-test="trend-empty"
        icon="fas fa-chart-column"
        text="该区间内暂无生产数据"
      />

      <div v-else data-test="trend-chart" ref="chartEl" class="h-[260px] w-full" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import type { EChartsType } from 'echarts/core'

import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import { ensureEcharts } from '@/utils/echartsPreload'
import type { TrendResponse } from '@/types'
import { buildTrendOption } from '../composables/trendChartOption'

const DAYS = 30

const props = defineProps<{
  trend: TrendResponse | null
  loading: boolean
}>()

const chartEl = ref<HTMLElement | null>(null)
let chart: EChartsType | null = null

const hasData = computed(() => !!props.trend?.days.some((d) => d.total > 0))

async function render() {
  if (!hasData.value || !chartEl.value) return
  const echarts = await ensureEcharts()
  if (!chartEl.value) return
  if (!chart || chart.isDisposed()) chart = echarts.init(chartEl.value)
  chart.setOption(buildTrendOption(props.trend!.days, props.trend!.departments), true)
  chart.resize()
}

function dispose() {
  chart?.dispose()
  chart = null
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  nextTick(render)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  dispose()
})

watch(
  () => [props.trend, hasData.value],
  () => {
    if (!hasData.value) {
      dispose()
      return
    }
    nextTick(render)
  },
)
</script>
```

**实现时注意**：`ensureEcharts()` 的返回类型来自 `src/utils/echartsPreload.ts`；若其导出的类型名不是 `EChartsModule` 或 `echarts.init` 不在其上，参照原 `useProductionCharts.ts` 的用法（它已经这样用并通过了类型检查）。`onBeforeUnmount` 里必须 `dispose()`，否则切页会泄漏 ECharts 实例 —— 这是原 `useProductionCharts.ts` 已有的纪律，不要退化。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/productionTrendPanel.render.test.ts`
Expected: PASS（5 passed）。测试环境是 jsdom、无 canvas，所以**测试只断言空态/骨架/容器是否存在，不断言画布内容** —— 图表内容由 Task 2 的纯函数测试覆盖。

- [ ] **Step 6: lint + type-check + 提交**

Run: `cd frontend-vite && npm run lint && npm run type-check`
Expected: 均无错误

```bash
git add frontend-vite/src/views/production/composables/productionDate.ts frontend-vite/src/views/production/composables/useProductionTrend.ts frontend-vite/src/views/production/components/ProductionTrendPanel.vue frontend-vite/src/test/productionTrendPanel.render.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): 新增近 30 日趋势面板（可跨月区间）

全 0 时渲染空态而非空白画布；组件卸载时 dispose 图表实例。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 5: 本月部门排行面板

**Files:**
- Create: `frontend-vite/src/views/production/components/DeptRankPanel.vue`
- Test: `frontend-vite/src/test/deptRankPanel.render.test.ts`

**Interfaces:**
- Consumes: `DEPT_LABELS`、`DEPT_COLORS`（Task 2）；`formatNumber`（`@/utils/format`）
- Produces: `DeptRankPanel` 组件 props：`{ departments: DepartmentSummary[]; loading: boolean }`

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/deptRankPanel.render.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import DeptRankPanel from '@/views/production/components/DeptRankPanel.vue'
import type { DepartmentSummary } from '@/types'

function dept(department: string, label: string, qty: number): DepartmentSummary {
  return { department, department_label: label, total_quantity: qty, total_value: qty * 7, sku_count: 2 }
}

describe('DeptRankPanel', () => {
  it('按产量降序渲染，第一名在最上', () => {
    const wrapper = mount(DeptRankPanel, {
      props: {
        departments: [dept('filling', '充棉部', 100), dept('packaging', '包装部', 300), dept('handcraft', '手工部', 200)],
        loading: false,
      },
    })

    const rows = wrapper.findAll('[data-test="rank-row"]')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.text()).toContain('包装部')
    expect(rows[1]!.text()).toContain('手工部')
    expect(rows[2]!.text()).toContain('充棉部')
  })

  it('受限用户只渲染返回的部门，不补三条', () => {
    // Review Focus #4
    const wrapper = mount(DeptRankPanel, {
      props: { departments: [dept('filling', '充棉部', 100)], loading: false },
    })

    expect(wrapper.findAll('[data-test="rank-row"]')).toHaveLength(1)
  })

  it('全部为 0 时渲染空态', () => {
    const wrapper = mount(DeptRankPanel, {
      props: { departments: [dept('filling', '充棉部', 0)], loading: false },
    })

    expect(wrapper.find('[data-test="rank-empty"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-test="rank-row"]')).toHaveLength(0)
  })

  it('加载中显示骨架', () => {
    const wrapper = mount(DeptRankPanel, { props: { departments: [], loading: true } })

    expect(wrapper.find('[data-test="rank-skeleton"]').exists()).toBe(true)
  })

  it('进度条宽度按"相对第一名的比例"给出，第一名占满', () => {
    const wrapper = mount(DeptRankPanel, {
      props: {
        departments: [dept('filling', '充棉部', 50), dept('packaging', '包装部', 200)],
        loading: false,
      },
    })

    const bars = wrapper.findAll('[data-test="rank-bar"]')
    expect(bars[0]!.attributes('style')).toContain('width: 100%')
    expect(bars[1]!.attributes('style')).toContain('width: 25%')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/deptRankPanel.render.test.ts`
Expected: FAIL —— 组件不存在

- [ ] **Step 3: 写组件**

创建 `frontend-vite/src/views/production/components/DeptRankPanel.vue`：

```vue
<template>
  <section class="page-card flex min-h-0 flex-col overflow-hidden">
    <header class="page-card-header">
      <span class="text-sm font-bold text-heading">
        <FontAwesomeIcon icon="ranking-star" class="mr-1.5 text-primary-500" aria-hidden="true" />
        本月部门排行
      </span>
      <span class="text-xs font-medium text-text-muted">按产量</span>
    </header>

    <div class="page-card-body">
      <UiSkeleton v-if="loading" data-test="rank-skeleton" variant="text" :rows="3" />

      <UiEmpty v-else-if="!ranked.length" data-test="rank-empty" icon="fas fa-ranking-star" text="本月暂无产量" />

      <ol v-else class="flex flex-col gap-3">
        <li v-for="(row, index) in ranked" :key="row.department" data-test="rank-row" class="flex items-center gap-2.5">
          <span class="w-4 shrink-0 text-xs font-bold text-text-muted">{{ index + 1 }}</span>
          <span class="w-14 shrink-0 text-xs font-bold text-heading">{{ label(row.department) }}</span>
          <span
            data-test="rank-bar"
            class="h-2 rounded-full"
            :style="{ width: barWidth(row), background: color(row.department) }"
          />
          <span class="ml-auto text-xs font-bold tabular-nums text-heading">{{ formatNumber(row.total_quantity) }}</span>
        </li>
      </ol>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import { formatNumber } from '@/utils/format'
import type { DepartmentSummary } from '@/types'
import { DEPT_COLORS, DEPT_LABELS } from '../composables/trendChartOption'

const props = defineProps<{
  departments: DepartmentSummary[]
  loading: boolean
}>()

/** 只保留有产量的部门，并按产量降序 —— 全 0 时得到空数组，于是走空态 */
const ranked = computed(() =>
  [...props.departments].filter((d) => d.total_quantity > 0).sort((a, b) => b.total_quantity - a.total_quantity),
)

const maxQuantity = computed(() => ranked.value[0]?.total_quantity ?? 0)

function barWidth(row: DepartmentSummary): string {
  if (!maxQuantity.value) return '0%'
  return `${Math.round((row.total_quantity / maxQuantity.value) * 100)}%`
}

function label(dept: string): string {
  return DEPT_LABELS[dept] ?? dept
}

function color(dept: string): string {
  return DEPT_COLORS[dept] ?? '#94a3b8'
}
</script>
```

**注意**：进度条宽度用 `Math.round(...)` 取整百分比 —— 测试断言 `width: 100%` / `width: 25%`，不要改成小数（如 `25.0%`），否则断言与实现都要跟着改。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/deptRankPanel.render.test.ts`
Expected: PASS（5 passed）

- [ ] **Step 5: lint + type-check + 提交**

Run: `cd frontend-vite && npm run lint && npm run type-check`
Expected: 均无错误

```bash
git add frontend-vite/src/views/production/components/DeptRankPanel.vue frontend-vite/src/test/deptRankPanel.render.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): 新增本月部门排行面板

按产量降序、条宽按相对第一名的比例；只渲染后端返回的可见部门。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 6: 部门下钻卡

**Files:**
- Create: `frontend-vite/src/views/production/components/DeptDrillCards.vue`
- Test: `frontend-vite/src/test/deptDrillCards.render.test.ts`

**Interfaces:**
- Consumes: `DEPT_LABELS`、`DEPT_COLORS`（Task 2）；`formatCurrency`、`formatNumber`（`@/utils/format`）
- Produces: `DeptDrillCards` 组件 props `{ departments: DepartmentSummary[]; loading: boolean }`；emits `drill: [department: string]`

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/deptDrillCards.render.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import DeptDrillCards from '@/views/production/components/DeptDrillCards.vue'
import type { DepartmentSummary } from '@/types'

function dept(department: string, label: string, qty: number, value: number): DepartmentSummary {
  return { department, department_label: label, total_quantity: qty, total_value: value, sku_count: 2 }
}

const three = [
  dept('filling', '充棉部', 1240, 8680),
  dept('handcraft', '手工部', 860, 12040),
  dept('packaging', '包装部', 2150, 6450),
]

describe('DeptDrillCards', () => {
  it('渲染后端返回的每个部门，显示件数与产值', () => {
    const wrapper = mount(DeptDrillCards, { props: { departments: three, loading: false } })

    expect(wrapper.findAll('[data-test="dept-card"]')).toHaveLength(3)
    expect(wrapper.text()).toContain('充棉部')
    expect(wrapper.text()).toContain('1,240')
  })

  it('点击卡片 emit drill 并带上部门键（不是中文名）', () => {
    const wrapper = mount(DeptDrillCards, { props: { departments: three, loading: false } })

    await wrapper.findAll('[data-test="dept-card"]')[2]!.trigger('click')

    expect(wrapper.emitted('drill')).toEqual([['packaging']])
  })

  it('受限用户只有一张卡时不补满三张', () => {
    // Review Focus #4
    const wrapper = mount(DeptDrillCards, { props: { departments: [three[0]!], loading: false } })

    expect(wrapper.findAll('[data-test="dept-card"]')).toHaveLength(1)
  })

  it('加载中显示骨架', () => {
    const wrapper = mount(DeptDrillCards, { props: { departments: [], loading: true } })

    expect(wrapper.find('[data-test="dept-skeleton"]').exists()).toBe(true)
  })

  it('无可见部门时渲染空态', () => {
    const wrapper = mount(DeptDrillCards, { props: { departments: [], loading: false } })

    expect(wrapper.find('[data-test="dept-empty"]').exists()).toBe(true)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/deptDrillCards.render.test.ts`
Expected: FAIL —— 组件不存在

- [ ] **Step 3: 写组件**

创建 `frontend-vite/src/views/production/components/DeptDrillCards.vue`：

```vue
<template>
  <div>
    <UiSkeleton v-if="loading" data-test="dept-skeleton" variant="card" :rows="1" />

    <UiEmpty v-else-if="!departments.length" data-test="dept-empty" icon="fas fa-industry" text="暂无可查看的部门" />

    <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-3">
      <button
        v-for="row in departments"
        :key="row.department"
        type="button"
        data-test="dept-card"
        class="flex items-center gap-3 rounded-[var(--radius-card)] border border-border-light bg-surface-card px-4 py-3 text-left transition-shadow hover:shadow-md"
        :style="{ borderLeft: `4px solid ${color(row.department)}` }"
        @click="emit('drill', row.department)"
      >
        <span class="min-w-0 flex-1">
          <span class="block text-xs font-bold text-heading">{{ label(row.department) }}</span>
          <span class="block text-lg font-extrabold tabular-nums text-heading">
            {{ formatNumber(row.total_quantity) }}
            <small class="text-[11px] font-semibold text-text-muted">件</small>
          </span>
          <span class="block text-[11px] font-medium text-text-muted">
            {{ formatCurrency(row.total_value) }} · {{ row.sku_count }} 种
          </span>
        </span>
        <FontAwesomeIcon icon="chevron-right" class="text-text-muted" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import { formatCurrency, formatNumber } from '@/utils/format'
import type { DepartmentSummary } from '@/types'
import { DEPT_COLORS, DEPT_LABELS } from '../composables/trendChartOption'

defineProps<{
  departments: DepartmentSummary[]
  loading: boolean
}>()

const emit = defineEmits<{
  drill: [department: string]
}>()

function label(dept: string): string {
  return DEPT_LABELS[dept] ?? dept
}

function color(dept: string): string {
  return DEPT_COLORS[dept] ?? '#94a3b8'
}
</script>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/deptDrillCards.render.test.ts`
Expected: PASS（5 passed）

- [ ] **Step 5: lint + type-check + 提交**

Run: `cd frontend-vite && npm run lint && npm run type-check`
Expected: 均无错误

```bash
git add frontend-vite/src/views/production/components/DeptDrillCards.vue frontend-vite/src/test/deptDrillCards.render.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

---

### Task 7: 后端补 `keyword` 筛选（前置，非前端）

**为什么在前端计划里**：设计规格 §4.2 要求明细抽屉支持"产品名或 69 码搜索"，但 Plan A 给 `/records` 增加的筛选参数里**没有**关键词参数 —— 后端目前搜不了。不补的话，前端只能做一个"只过滤当前页"的假搜索，那比没有更糟。

**Files:**
- Modify: `fastapi_app/services/daily_production_service.py`（`_build_record_conditions`、`get_records`）
- Modify: `fastapi_app/api/v1/endpoints/daily_production.py`（`list_records`）
- Test: `fastapi_app/tests/test_daily_production_records_filter.py`（追加用例）

**Interfaces:**
- Produces: `GET /api/v1/daily-production/records` 新增可选 `keyword` 参数；`get_records(..., keyword: str = '')`；`_build_record_conditions(..., keyword: str = '')`

- [ ] **Step 1: 先确认转义工具**

Run: `command grep -rn "def escape_like" fastapi_app/`
- 若有该函数：按它的签名使用，`LIKE` 时传 `escape='\\'`。
- 若没有：手写转义 —— 把用户输入里的 `\`、`%`、`_` 依次替换为 `\\`、`\%`、`\_`，再拼 `%...%`，并在 `.like(pattern, escape='\\')` 里声明转义符。
**不要**直接把用户输入拼进 `%{kw}%` 而不转义：`%` 与 `_` 是 LIKE 的通配符，搜 "50%" 会变成"以 50 开头"。

- [ ] **Step 2: 写失败的测试**

在 `fastapi_app/tests/test_daily_production_records_filter.py` 的 `TestRecordConditions` 里追加：

```python
    def test_blank_keyword_is_not_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', keyword='',
        )
        assert 'product_name' not in _texts(conditions)

    def test_whitespace_keyword_is_not_applied(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', keyword='   ',
        )
        assert 'product_name' not in _texts(conditions)

    def test_keyword_matches_product_name_or_barcode(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', keyword='白兔',
        )
        rendered = _texts(conditions)
        assert 'product_name' in rendered
        assert 'barcode' in rendered
        assert len(conditions) == 3

    def test_keyword_like_wildcards_are_escaped(self):
        conditions = _build_record_conditions(
            year=2026, month=9, start_date='', end_date='',
            departments=None, created_by='', keyword='50%',
        )
        # 绑定参数里必须是转义后的字面量，而不是裸的 % 通配
        assert '50\\%' in _texts(conditions)
```

（`_texts` 辅助函数已存在于该文件；`_build_record_conditions` 的其余调用点因为新参数带默认值，不需要改动。）

- [ ] **Step 3: 跑测试确认失败**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_records_filter.py -q --no-header`
Expected: FAIL —— `TypeError: _build_record_conditions() got an unexpected keyword argument 'keyword'`

- [ ] **Step 4: 实现**

a) `fastapi_app/services/daily_production_service.py`：把 `from sqlalchemy import and_, func, select` 改为 `from sqlalchemy import and_, func, or_, select`。

b) `_build_record_conditions` 的签名加 `keyword: str = ''`（放在 `production_date: str = ''` 之后），docstring 的 Args 里补一行，并在函数体 `return conditions` 之前加：

```python
    if keyword and keyword.strip():
        pattern = f'%{_escape_like(keyword.strip())}%'
        conditions.append(
            or_(
                DailyProductionRecord.product_name.like(pattern, escape='\\'),
                DailyProductionRecord.barcode == keyword.strip(),
            )
        )
```

c) 在同一文件里加转义辅助函数（若 Step 1 已找到仓库既有的 `escape_like`，改为 import 它，不要重复实现）：

```python
def _escape_like(value: str) -> str:
    """转义 LIKE 通配符，避免用户输入的 % / _ 被当成通配符"""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
```

d) `get_records` 的签名加 `keyword: str = ''`，并在构造条件处传入：

```python
    conditions = _build_record_conditions(
        year=year, month=month, start_date=start_date, end_date=end_date,
        departments=departments, created_by=created_by,
        production_date=production_date, keyword=keyword,
    )
```

e) `fastapi_app/api/v1/endpoints/daily_production.py` 的 `list_records`：加查询参数

```python
    keyword: str = Query('', description='产品名或 69 码关键词；留空为不限'),
```

并把它透传给 `get_records`（`keyword=keyword`）。docstring 的 Args 里补一行。

- [ ] **Step 5: 跑测试确认通过**

Run: `command python -m pytest fastapi_app/tests/test_daily_production_records_filter.py -q --no-header`
Expected: PASS（原 11 条 + 新 4 条 = 15 passed）

- [ ] **Step 6: 回归 + 门禁 + lint**

Run:
```bash
command python -m pytest tests/test_daily_production.py tests/test_production_attribution.py tests/test_production_plan_service.py fastapi_app/tests/ -q --no-header -k "production or scope or daily"
command python scripts/quality_gate.py
command python -m ruff check fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py
```
Expected: 全部 PASS / 无输出。**注意 80 行函数门禁**：`get_records` 已在基线内（超限但已计入），本改动只增几行不会改变违规计数；但**不得**把任何别的函数推过 80 行，也**绝不**用 `--no-verify`、**绝不**改 `scripts/gate_baseline.json`。

- [ ] **Step 7: 提交**

```bash
git add fastapi_app/services/daily_production_service.py fastapi_app/api/v1/endpoints/daily_production.py fastapi_app/tests/test_daily_production_records_filter.py
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): /records 支持产品名/69码关键词筛选

设计规格 §4.2 要求明细抽屉可搜产品，但 Plan A 未实现该参数；
LIKE 通配符按字面量转义，避免 % / _ 被当成通配符。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 8: 明细筛选状态与请求参数（纯函数）+ 记录 composable

**Files:**
- Create: `frontend-vite/src/views/production/composables/recordFilters.ts`
- Create: `frontend-vite/src/views/production/composables/useProductionRecords.ts`
- Test: `frontend-vite/src/test/productionRecordFilters.test.ts`

**Interfaces:**
- Consumes: `RecordsQuery`（Task 1）；`dailyProductionApi.records / createRecord / updateRecord / deleteRecord`（Task 1）；`keyword` 参数（Task 7）；`toLocalDate` / `mondayOf`（Task 4 的 `productionDate.ts` —— **不要在本文件再写一份**）
- Produces:
  - `RangePreset = 'today' | 'week' | 'month' | 'custom'`
  - `RecordFilters` 接口、`defaultRecordFilters(): RecordFilters`
  - `buildRecordsQuery(filters: RecordFilters, today?: Date): RecordsQuery`
  - `useProductionRecords(filters: Ref<RecordFilters>)` → `{ recordsQuery, removeRecord }`

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/productionRecordFilters.test.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { buildRecordsQuery, defaultRecordFilters } from '@/views/production/composables/recordFilters'

// 固定"今天"为周三，便于断言"本周"
const WED = new Date(2026, 8, 30) // 2026-09-30

function filters(overrides: Partial<ReturnType<typeof defaultRecordFilters>> = {}) {
  return { ...defaultRecordFilters(), ...overrides }
}

describe('buildRecordsQuery', () => {
  it('本月：只传 year/month，不传区间', () => {
    const q = buildRecordsQuery(filters({ preset: 'month' }), WED)

    expect(q).toEqual({ year: 2026, month: 9, page: 1, per_page: 50, sort: 'desc' })
  })

  it('今日：传当月 year/month 加 production_date 单日', () => {
    const q = buildRecordsQuery(filters({ preset: 'today' }), WED)

    expect(q).toEqual({ year: 2026, month: 9, production_date: '2026-09-30', page: 1, per_page: 50, sort: 'desc' })
  })

  it('本周：从本周一到今天，走区间且不带 year/month', () => {
    // Review Focus #5：本周可能跨月
    const q = buildRecordsQuery(filters({ preset: 'week' }), WED)

    expect(q.start_date).toBe('2026-09-28')
    expect(q.end_date).toBe('2026-09-30')
    expect(q).not.toHaveProperty('year')
    expect(q).not.toHaveProperty('month')
  })

  it('自定义：区间原样透传，不带 year/month', () => {
    const q = buildRecordsQuery(
      filters({ preset: 'custom', customStart: '2026-08-25', customEnd: '2026-09-02' }),
      WED,
    )

    expect(q.start_date).toBe('2026-08-25')
    expect(q.end_date).toBe('2026-09-02')
    expect(q).not.toHaveProperty('year')
  })

  it('自定义区间只填了一半时回退到本月，不发出半个区间', () => {
    const q = buildRecordsQuery(filters({ preset: 'custom', customStart: '2026-08-25', customEnd: '' }), WED)

    expect(q).toEqual({ year: 2026, month: 9, page: 1, per_page: 50, sort: 'desc' })
  })

  it('自定义区间反向时回退到本月', () => {
    const q = buildRecordsQuery(
      filters({ preset: 'custom', customStart: '2026-09-10', customEnd: '2026-09-01' }),
      WED,
    )

    expect(q).not.toHaveProperty('start_date')
  })

  it('空部门不传 department 键', () => {
    const q = buildRecordsQuery(filters({ department: '' }), WED)

    expect(q).not.toHaveProperty('department')
  })

  it('指定部门时传 department', () => {
    const q = buildRecordsQuery(filters({ department: 'filling' }), WED)

    expect(q.department).toBe('filling')
  })

  it('录单人留空时不传 created_by 键（绝不能传空串）', () => {
    // Review Focus #5：传 created_by='' 会被后端当成"只看录单人为空的记录"
    const q = buildRecordsQuery(filters({ createdBy: '   ' }), WED)

    expect(q).not.toHaveProperty('created_by')
  })

  it('录单人有值时去掉首尾空格再传', () => {
    const q = buildRecordsQuery(filters({ createdBy: ' 张三 ' }), WED)

    expect(q.created_by).toBe('张三')
  })

  it('关键词留空时不传 keyword 键', () => {
    const q = buildRecordsQuery(filters({ keyword: '  ' }), WED)

    expect(q).not.toHaveProperty('keyword')
  })

  it('关键词有值时去掉首尾空格再传', () => {
    const q = buildRecordsQuery(filters({ keyword: ' 白兔 ' }), WED)

    expect(q.keyword).toBe('白兔')
  })

  it('页码与每页条数原样带上', () => {
    const q = buildRecordsQuery(filters({ page: 3, perPage: 100 }), WED)

    expect(q.page).toBe(3)
    expect(q.per_page).toBe(100)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/productionRecordFilters.test.ts`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 写筛选纯函数**

创建 `frontend-vite/src/views/production/composables/recordFilters.ts`：

```ts
/**
 * 明细抽屉的筛选状态 → 请求参数。
 *
 * 抽成纯函数的原因：这里有一批容易写错、且错了不容易看出来的边界 ——
 * 本周可能跨月（必须走区间）、自定义区间只填一半或填反（必须回退而不是发出去）、
 * 录单人/关键词留空（必须省略键而不是传空串 —— 后端会把空串当成"等于空"）。
 */
import type { RecordsQuery } from '@/types'
import { mondayOf, toLocalDate } from './productionDate'

export type RangePreset = 'today' | 'week' | 'month' | 'custom'

export interface RecordFilters {
  preset: RangePreset
  customStart: string
  customEnd: string
  department: string
  createdBy: string
  keyword: string
  page: number
  perPage: number
}

export function defaultRecordFilters(): RecordFilters {
  return {
    preset: 'month',
    customStart: '',
    customEnd: '',
    department: '',
    createdBy: '',
    keyword: '',
    page: 1,
    perPage: 50,
  }
}

function isReversed(start: string, end: string): boolean {
  return !!start && !!end && end < start
}

export function buildRecordsQuery(filters: RecordFilters, today: Date = new Date()): RecordsQuery {
  const query: RecordsQuery = {
    page: filters.page,
    per_page: filters.perPage,
    sort: 'desc',
  }

  const y = today.getFullYear()
  const m = today.getMonth() + 1

  if (filters.preset === 'custom' && filters.customStart && filters.customEnd && !isReversed(filters.customStart, filters.customEnd)) {
    query.start_date = filters.customStart
    query.end_date = filters.customEnd
  } else if (filters.preset === 'week') {
    query.start_date = toLocalDate(mondayOf(today))
    query.end_date = toLocalDate(today)
  } else if (filters.preset === 'today') {
    query.year = y
    query.month = m
    query.production_date = toLocalDate(today)
  } else {
    // 'month'，以及自定义区间填了一半/填反时的回退
    query.year = y
    query.month = m
  }

  if (filters.department) query.department = filters.department
  if (filters.createdBy.trim()) query.created_by = filters.createdBy.trim()
  if (filters.keyword.trim()) query.keyword = filters.keyword.trim()

  return query
}
```

**注意**：`RecordsQuery` 里已有 `keyword?: string`（Task 1 定义时就要加上 —— 若 Task 1 未加，本任务先补上该字段）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/productionRecordFilters.test.ts`
Expected: PASS（13 passed）

- [ ] **Step 5: 写 records composable**

创建 `frontend-vite/src/views/production/composables/useProductionRecords.ts`：

```ts
/**
 * 明细记录的查询与增删改。
 *
 * queryKey 必须包含**完整筛选条件**（含页码与每页条数）：抽屉的分页/筛选切换
 * 各自是独立缓存条目，否则翻页会命中上一页的缓存。这与后端移动看板那次
 * 「缓存键不含范围 → 跨用户串读」是同一类问题。
 */
import { computed, type Ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { dailyProductionApi } from '@/api/production'
import type { RecordFilters } from './recordFilters'
import { buildRecordsQuery } from './recordFilters'

export function useProductionRecords(filters: Ref<RecordFilters>) {
  const queryClient = useQueryClient()

  const query = computed(() => buildRecordsQuery(filters.value))

  const recordsQuery = useQuery({
    queryKey: computed(() => ['daily-production-records', query.value]),
    queryFn: () => dailyProductionApi.records(query.value),
    staleTime: 30_000,
  })

  function invalidateAll() {
    queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-trend'] })
  }

  const removeRecord = useMutation({
    mutationFn: (id: number) => dailyProductionApi.deleteRecord(id),
    onSuccess: invalidateAll,
  })

  return { recordsQuery, removeRecord, invalidateAll }
}
```

- [ ] **Step 6: lint + type-check + 提交**

Run: `cd frontend-vite && npm run lint && npm run type-check`
Expected: 均无错误

```bash
git add frontend-vite/src/views/production/composables/recordFilters.ts frontend-vite/src/views/production/composables/useProductionRecords.ts frontend-vite/src/test/productionRecordFilters.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): 明细筛选纯函数与记录查询 composable

本周/自定义走跨月区间、区间填一半或填反回退到本月、
录单人与关键词留空时省略键而非传空串。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 9: 明细抽屉

**Files:**
- Create: `frontend-vite/src/views/production/components/RecordDrawer.vue`
- Create: `frontend-vite/src/views/production/components/RecordFilterBar.vue`
- Test: `frontend-vite/src/test/recordDrawer.render.test.ts`

**Interfaces:**
- Consumes: `UiDrawer`、`UiDataTable`（`TableColumn`、`column-body-{field}` 插槽、`paginator`/`totalRecords`/`@page`）、`UiDateRangePicker`、`UiSearchInput`、`UiSelect`、`UiEmpty`、`UiConfirmDialog`；`RecordFilters` / `defaultRecordFilters`（Task 8）；`useProductionRecords`（Task 8）；`DEPT_LABELS`（Task 2）
- Produces: `RecordDrawer` 组件 props `{ open: boolean; presetDepartment?: string }`；emits `update:open: [boolean]`、`edit: [record: DailyProductionRecord]`、`create: []`

- [ ] **Step 1: 先读清 `UiDataTable` 的分页语义**

Run: `command sed -n '120,220p' frontend-vite/src/components/ui/UiDataTable.vue`

**必须确认** `@page` 事件里 `page` 是 1 基还是 0 基（PrimeVue 原生是 0 基，本仓库的封装可能已经 +1）。参照既有可用范例：`frontend-vite/src/components/backup/BackupRecordTable.vue` 与它的测试 `frontend-vite/src/test/backupRecordTablePaging.test.ts`（该测试断言 `emitted('page-change')` 为 `[[1], [3]]`，说明该项目里的分页事件是 1 基的）。**按你读到的事实写**，不要照抄本任务的假设。

- [ ] **Step 2: 写失败的测试**

创建 `frontend-vite/src/test/recordDrawer.render.test.ts`：

```ts
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import RecordDrawer from '@/views/production/components/RecordDrawer.vue'
import type { DailyProductionRecord } from '@/types'

const record: DailyProductionRecord = {
  id: 7,
  department: 'filling',
  product_name: '白兔公仔 40cm',
  barcode: '6901234',
  unit_price: 7,
  quantity: 620,
  production_value: 4340,
  production_date: '2026-09-29',
  remark: '',
  created_by: '张三',
}

function mountDrawer(props: Record<string, unknown> = {}) {
  return mount(RecordDrawer, {
    props: { open: true, records: [record], total: 128, pages: 3, stats: null, loading: false, ...props },
    global: { stubs: { UiDrawer: { template: '<div><slot /><slot name="footer" /></div>' } } },
  })
}

describe('RecordDrawer', () => {
  it('渲染表格行与产品名', () => {
    const wrapper = mountDrawer()

    expect(wrapper.text()).toContain('白兔公仔 40cm')
    expect(wrapper.findAll('[data-test="record-row"]').length).toBeGreaterThan(0)
  })

  it('stats 为 null 时合计显示 0，不显示 NaN 或空白', () => {
    // Review Focus #1
    const wrapper = mountDrawer({ stats: null, records: [] })

    const summary = wrapper.find('[data-test="drawer-summary"]')
    expect(summary.text()).toContain('0')
    expect(summary.text()).not.toContain('NaN')
    expect(summary.text()).not.toContain('undefined')
  })

  it('stats 有值时合计显示条数与产量', () => {
    const wrapper = mountDrawer({
      stats: { total_quantity: 4250, total_value: 27170, total_sku: 18 },
    })

    const summary = wrapper.find('[data-test="drawer-summary"]')
    expect(summary.text()).toContain('4,250')
    expect(summary.text()).toContain('18')
  })

  it('点击删除会请求确认，确认文本含产品名与数量', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-delete"]').trigger('click')

    expect(wrapper.find('[data-test="delete-confirm"]').text()).toContain('白兔公仔 40cm')
    expect(wrapper.find('[data-test="delete-confirm"]').text()).toContain('620')
  })

  it('取消删除时不 emit confirm-delete', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-delete"]').trigger('click')
    await wrapper.find('[data-test="delete-cancel"]').trigger('click')

    expect(wrapper.emitted('confirm-delete')).toBeUndefined()
  })

  it('确认删除时 emit confirm-delete 并带上记录 id', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-delete"]').trigger('click')
    await wrapper.find('[data-test="delete-confirm-btn"]').trigger('click')

    expect(wrapper.emitted('confirm-delete')).toEqual([[7]])
  })

  it('点改 emit edit 并带上整条记录', async () => {
    const wrapper = mountDrawer()

    await wrapper.find('[data-test="record-edit"]').trigger('click')

    expect(wrapper.emitted('edit')?.[0]?.[0]).toMatchObject({ id: 7 })
  })

  it('无记录时渲染空态而不是空表', () => {
    const wrapper = mountDrawer({ records: [], total: 0, pages: 0 })

    expect(wrapper.find('[data-test="records-empty"]').exists()).toBe(true)
  })
})
```

**注意**：为了让上面的测试可行，`RecordDrawer` 设计为**纯展示 + emit**（数据由父组件传入），删除确认的对话框放在组件内部但由 `confirm-delete` 事件把决定交给父组件执行。这样测试不需要 mock 网络。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/recordDrawer.render.test.ts`
Expected: FAIL —— 组件不存在

- [ ] **Step 4: 写筛选条组件**

创建 `frontend-vite/src/views/production/components/RecordFilterBar.vue`：

```vue
<template>
  <div class="flex flex-wrap items-center gap-2 border-b border-border-light bg-surface-card px-4 py-2.5">
    <div class="flex items-center gap-1 rounded-lg bg-surface-sunken p-0.5">
      <button
        v-for="p in PRESETS"
        :key="p.value"
        type="button"
        class="rounded-md px-2.5 py-1 text-xs font-semibold transition-colors"
        :class="filters.preset === p.value ? 'bg-primary-600 text-white' : 'text-text-secondary hover:text-heading'"
        @click="emit('update:filters', { ...filters, preset: p.value, page: 1 })"
      >
        {{ p.label }}
      </button>
    </div>

    <UiDateRangePicker
      v-if="filters.preset === 'custom'"
      :model-value="customRange"
      placeholder="选择区间"
      @update:model-value="onCustomRange"
    />

    <UiSelect
      :model-value="filters.department"
      :options="deptOptions"
      placeholder="全部部门"
      @update:model-value="(v: string) => emit('update:filters', { ...filters, department: v ?? '', page: 1 })"
    />

    <UiSearchInput
      :model-value="filters.keyword"
      placeholder="产品名或 69 码…"
      @update:model-value="(v: string) => emit('update:filters', { ...filters, keyword: v })"
      @search="emit('search')"
    />

    <UiSelect
      v-if="createdByOptions.length > 1"
      :model-value="filters.createdBy"
      :options="createdByOptions"
      placeholder="全部录单人"
      @update:model-value="(v: string) => emit('update:filters', { ...filters, createdBy: v ?? '', page: 1 })"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import UiDateRangePicker from '@/components/ui/UiDateRangePicker.vue'
import UiSearchInput from '@/components/ui/UiSearchInput.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import { DEPT_LABELS } from '../composables/trendChartOption'
import type { RecordFilters } from '../composables/recordFilters'

const PRESETS = [
  { label: '今日', value: 'today' },
  { label: '本周', value: 'week' },
  { label: '本月', value: 'month' },
  { label: '自定义', value: 'custom' },
] as const

const props = defineProps<{
  filters: RecordFilters
  /** 后端返回的可见部门键；只列这些，不硬编码三个 */
  departments: string[]
  /** 可选的录单人；少于 2 个时该筛选器不显示（避免只有一个选项的下拉） */
  createdByOptions: Array<{ label: string; value: string }>
}>()

const emit = defineEmits<{
  'update:filters': [value: RecordFilters]
  search: []
}>()

const deptOptions = computed(() => [
  { label: '全部部门', value: '' },
  ...props.departments.map((d) => ({ label: DEPT_LABELS[d] ?? d, value: d })),
])

const customRange = computed<[string, string] | null>(() =>
  props.filters.customStart && props.filters.customEnd
    ? [props.filters.customStart, props.filters.customEnd]
    : null,
)

function onCustomRange(value: [string, string] | null) {
  emit('update:filters', {
    ...props.filters,
    customStart: value?.[0] ?? '',
    customEnd: value?.[1] ?? '',
    page: 1,
  })
}
</script>
```

**实现时确认** `UiSelect` 的确切 props（`model-value` 与 `options` 的形状、是否有 `placeholder`）—— 读 `frontend-vite/src/components/ui/UiSelect.vue` 后按实际签名写；若它用的是 `v-model` 与 `optionLabel`/`optionValue` 这类 PrimeVue 风格 prop，就照它写。

- [ ] **Step 5: 写抽屉组件**

创建 `frontend-vite/src/views/production/components/RecordDrawer.vue`（**目标 ≤ 400 行**；若逼近上限，把表格列定义与删除确认拆成子组件）：

```vue
<template>
  <UiDrawer
    :visible="open"
    title="生产明细"
    width="960px"
    @update:visible="emit('update:open', $event)"
  >
    <RecordFilterBar
      :filters="filters"
      :departments="departments"
      :created-by-options="createdByOptions"
      @update:filters="emit('update:filters', $event)"
      @search="emit('search')"
    />

    <div data-test="drawer-summary" class="flex flex-wrap items-center gap-3 border-b border-border-light px-4 py-2 text-xs font-semibold text-text-secondary">
      <span>共 {{ total }} 条</span>
      <span>合计产量 {{ formatNumber(summaryQuantity) }} 件</span>
      <span>合计产值 {{ formatCurrency(summaryValue) }}</span>
      <span v-if="summarySku !== null">涉及 {{ summarySku }} 个品种</span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col">
      <UiSkeleton v-if="loading" variant="table" :rows="6" />

      <UiEmpty v-else-if="!records.length" data-test="records-empty" icon="fas fa-inbox" text="当前筛选下暂无记录" />

      <UiDataTable
        v-else
        :data="records"
        :columns="COLUMNS"
        row-key="id"
        paginator
        :rows="filters.perPage"
        :total-records="total"
        @page="onPage"
      >
        <template #column-body-department="{ row }">
          <span class="rounded bg-surface-sunken px-1.5 py-0.5 text-[11px] font-bold">
            {{ DEPT_LABELS[row.department] ?? row.department }}
          </span>
        </template>
        <template #column-body-production_date="{ row }">{{ row.production_date }}</template>
        <template #column-body-quantity="{ row }">
          <strong class="tabular-nums">{{ formatNumber(row.quantity) }}</strong>
        </template>
        <template #column-body-production_value="{ row }">{{ formatCurrency(row.production_value) }}</template>
        <template #column-body-actions="{ row }">
          <span data-test="record-row" class="flex gap-2">
            <button data-test="record-edit" class="text-xs font-bold text-primary-600" @click="emit('edit', row)">改</button>
            <button data-test="record-delete" class="text-xs font-bold text-danger-600" @click="askDelete(row)">删</button>
          </span>
        </template>
      </UiDataTable>
    </div>

    <UiConfirmDialog
      :open="!!pendingDelete"
      data-test="delete-confirm"
      type="danger"
      :text="`确认删除这条生产记录？`"
      :sub="pendingDelete ? `${pendingDelete.product_name} · ${pendingDelete.quantity} 件 · ${pendingDelete.production_date} · ${DEPT_LABELS[pendingDelete.department] ?? pendingDelete.department}` : ''"
      @confirm="confirmDelete"
      @cancel="pendingDelete = null"
    />
  </UiDrawer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import { formatCurrency, formatNumber } from '@/utils/format'
import type { DailyProductionRecord, ProductionRecordStats } from '@/types'
import { DEPT_LABELS } from '../composables/trendChartOption'
import RecordFilterBar from './RecordFilterBar.vue'
import type { RecordFilters } from '../composables/recordFilters'

const COLUMNS: TableColumn[] = [
  { field: 'production_date', header: '日期', width: '96px' },
  { field: 'department', header: '部门', width: '80px', align: 'center' },
  { field: 'product_name', header: '产品' },
  { field: 'barcode', header: '69 码', width: '110px' },
  { field: 'quantity', header: '数量', width: '80px', align: 'right' },
  { field: 'production_value', header: '产值', width: '100px', align: 'right' },
  { field: 'remark', header: '备注' },
  { field: 'created_by', header: '录单人', width: '90px' },
  { field: 'actions', header: '操作', width: '80px', align: 'center' },
]
```

**关于列集合的一处刻意偏离**：规格 §4.2 的列清单里还有"单价"。本实现**不展示单价列** —— 产值 = 单价 × 数量，两者并列属于重复信息，而抽屉可用宽度约 960px，十列会挤到每列都要截断。单价仍可在编辑弹窗里查看与修改（Task 10）。**这是有意的取舍，不是遗漏**；如果评审认为必须显示，加一列 `{ field: 'unit_price', header: '单价', width: '90px', align: 'right' }` 并相应把 `barcode` 或 `remark` 去掉即可。

```ts

const props = defineProps<{
  open: boolean
  filters: RecordFilters
  records: DailyProductionRecord[]
  total: number
  stats: ProductionRecordStats | null
  loading: boolean
  departments: string[]
  createdByOptions: Array<{ label: string; value: string }>
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'update:filters': [value: RecordFilters]
  search: []
  edit: [record: DailyProductionRecord]
  'confirm-delete': [id: number]
}>()

const pendingDelete = ref<DailyProductionRecord | null>(null)

/** stats 为 null（当前筛选无记录）时一律显示 0 —— 绝不显示 NaN 或空白 */
const summaryQuantity = computed(() => props.stats?.total_quantity ?? 0)
const summaryValue = computed(() => props.stats?.total_value ?? 0)
const summarySku = computed(() => props.stats?.total_sku ?? null)

function askDelete(row: DailyProductionRecord) {
  pendingDelete.value = row
}

function confirmDelete() {
  if (pendingDelete.value) emit('confirm-delete', pendingDelete.value.id)
  pendingDelete.value = null
}

function onPage(event: { page: number; rows: number }) {
  emit('update:filters', { ...props.filters, page: event.page, perPage: event.rows })
}
</script>
```

**注意**：`UiConfirmDialog` 目前没有 `data-test` 透传到根元素的保证 —— 若测试拿不到 `[data-test="delete-confirm"]`，改为在测试里断言 `wrapper.text()` 包含产品名与数量，或在 `RecordDrawer` 里用一个自有的 `<div data-test="delete-confirm">` 包住它。**不要**为了测试去改 `UiConfirmDialog`（那是共享组件，改动面过大）。

**另一个可能踩到的坑**：`UiDataTable` 内部是 PrimeVue `DataTable`。若 jsdom 下 `[data-test="record-row"]` 找不到（PrimeVue 组件有时需要插件才能渲染），先试着给 `mount` 的 `global.plugins` 加 PrimeVue 插件，而不是把 `UiDataTable` stub 掉 —— stub 掉就等于不测表格了。仓库里 `src/test/backupRecordTablePaging.test.ts` 是同类表格测试的可用范例，照它的挂载方式写。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/recordDrawer.render.test.ts`
Expected: PASS（8 passed）

- [ ] **Step 7: lint + type-check + 提交**

Run: `cd frontend-vite && npm run lint && npm run type-check`
Expected: 均无错误

```bash
git add frontend-vite/src/views/production/components/RecordDrawer.vue frontend-vite/src/views/production/components/RecordFilterBar.vue frontend-vite/src/test/recordDrawer.render.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): 新增生产明细抽屉

筛选条 + 表格 + 分页 + 删除二次确认（确认文本含产品名/数量/日期/部门）；
stats 为 null 时合计显示 0。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 10: 记录编辑弹窗

**Files:**
- Create: `frontend-vite/src/views/production/components/RecordEditDialog.vue`
- Test: `frontend-vite/src/test/recordEditDialog.submit.test.ts`

**Interfaces:**
- Consumes: `UiDialog`（读它的 props/emits 后按实际签名用）、`UiInput`、`UiInputNumber`、`UiSelect`；`dailyProductionApi.updateRecord`（Task 1）
- Produces: `RecordEditDialog` 组件 props `{ open: boolean; record: DailyProductionRecord | null }`；emits `update:open: [boolean]`、`saved: []`

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/recordEditDialog.submit.test.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const updateMock = vi.fn()
vi.mock('@/api/production', () => ({
  dailyProductionApi: { updateRecord: (...a: unknown[]) => updateMock(...a) },
}))

import RecordEditDialog from '@/views/production/components/RecordEditDialog.vue'
import type { DailyProductionRecord } from '@/types'

const record: DailyProductionRecord = {
  id: 7,
  department: 'filling',
  product_name: '白兔公仔 40cm',
  barcode: '6901234',
  unit_price: 7,
  quantity: 620,
  production_value: 4340,
  production_date: '2026-09-29',
  remark: '',
  created_by: '张三',
}

describe('RecordEditDialog', () => {
  beforeEach(() => {
    updateMock.mockReset()
    updateMock.mockResolvedValue({ success: true, message: 'ok' })
  })

  it('只提交被改动过的字段', async () => {
    const wrapper = mount(RecordEditDialog, {
      props: { open: true, record },
      global: { stubs: { teleport: true } },
    })

    await wrapper.find('[data-test="edit-quantity"]').setValue('700')
    await wrapper.find('[data-test="edit-submit"]').trigger('click')
    await flushPromises()

    expect(updateMock).toHaveBeenCalledWith(7, { quantity: 700 })
  })

  it('没有改动时不提交，只关闭', async () => {
    const wrapper = mount(RecordEditDialog, {
      props: { open: true, record },
      global: { stubs: { teleport: true } },
    })

    await wrapper.find('[data-test="edit-submit"]').trigger('click')
    await flushPromises()

    expect(updateMock).not.toHaveBeenCalled()
    expect(wrapper.emitted('update:open')).toEqual([[false]])
  })

  it('数量改为 0 时拒绝提交并给出提示', async () => {
    const wrapper = mount(RecordEditDialog, {
      props: { open: true, record },
      global: { stubs: { teleport: true } },
    })

    await wrapper.find('[data-test="edit-quantity"]').setValue('0')
    await wrapper.find('[data-test="edit-submit"]').trigger('click')
    await flushPromises()

    expect(updateMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('大于 0')
  })

  it('保存成功后 emit saved', async () => {
    const wrapper = mount(RecordEditDialog, {
      props: { open: true, record },
      global: { stubs: { teleport: true } },
    })

    await wrapper.find('[data-test="edit-remark"]').setValue('补录')
    await wrapper.find('[data-test="edit-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/recordEditDialog.submit.test.ts`
Expected: FAIL —— 组件不存在

- [ ] **Step 3: 写组件**

创建 `frontend-vite/src/views/production/components/RecordEditDialog.vue`：

```vue
<template>
  <UiDialog :open="open" title="编辑生产记录" @update:open="emit('update:open', $event)">
    <div v-if="record" class="flex flex-col gap-4">
      <div class="rounded-lg bg-surface-sunken px-3 py-2 text-xs text-text-secondary">
        {{ record.product_name }} · {{ record.barcode || '无 69 码' }} · 原录单人 {{ record.created_by || '—' }}
      </div>

      <label class="flex flex-col gap-1.5">
        <span class="text-xs font-bold text-text-secondary">生产日期</span>
        <input v-model="form.production_date" data-test="edit-date" type="date" class="rounded-lg border border-border-light px-3 py-2 text-sm" />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="text-xs font-bold text-text-secondary">数量</span>
        <input v-model.number="form.quantity" data-test="edit-quantity" type="number" min="0" class="rounded-lg border border-border-light px-3 py-2 text-sm tabular-nums" />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="text-xs font-bold text-text-secondary">单价</span>
        <input v-model.number="form.unit_price" data-test="edit-price" type="number" min="0" step="0.01" class="rounded-lg border border-border-light px-3 py-2 text-sm tabular-nums" />
      </label>

      <label class="flex flex-col gap-1.5">
        <span class="text-xs font-bold text-text-secondary">备注</span>
        <input v-model="form.remark" data-test="edit-remark" type="text" class="rounded-lg border border-border-light px-3 py-2 text-sm" />
      </label>

      <p v-if="error" class="text-xs font-semibold text-danger-600">{{ error }}</p>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <button class="rounded-lg border border-border-light px-4 py-2 text-sm font-semibold" @click="emit('update:open', false)">取消</button>
        <button data-test="edit-submit" class="rounded-lg bg-primary-600 px-4 py-2 text-sm font-bold text-white" :disabled="saving" @click="submit">
          保存
        </button>
      </div>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'

import UiDialog from '@/components/ui/UiDialog.vue'
import { dailyProductionApi } from '@/api/production'
import type { DailyProductionRecord } from '@/types'

const props = defineProps<{
  open: boolean
  record: DailyProductionRecord | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  saved: []
}>()

const saving = ref(false)
const error = ref('')

const form = reactive({
  production_date: '',
  quantity: 0,
  unit_price: 0,
  remark: '',
})

const original = reactive({ production_date: '', quantity: 0, unit_price: 0, remark: '' })

watch(
  () => [props.open, props.record] as const,
  () => {
    if (!props.open || !props.record) return
    form.production_date = props.record.production_date
    form.quantity = props.record.quantity
    form.unit_price = props.record.unit_price
    form.remark = props.record.remark ?? ''
    Object.assign(original, form)
    error.value = ''
  },
  { immediate: true },
)

/** 只提交改动过的字段：后端 PUT 接受部分字段，未改动的字段不该被覆盖（尤其是没动单价时不该用 0 覆盖） */
function changedFields(): Record<string, unknown> {
  const diff: Record<string, unknown> = {}
  if (form.production_date !== original.production_date) diff.production_date = form.production_date
  if (form.quantity !== original.quantity) diff.quantity = form.quantity
  if (form.unit_price !== original.unit_price) diff.unit_price = form.unit_price
  if (form.remark !== original.remark) diff.remark = form.remark
  return diff
}

async function submit() {
  if (!props.record) return
  if (!form.quantity || form.quantity <= 0) {
    error.value = '生产数量必须大于 0'
    return
  }
  const diff = changedFields()
  if (!Object.keys(diff).length) {
    emit('update:open', false)
    return
  }

  saving.value = true
  error.value = ''
  try {
    await dailyProductionApi.updateRecord(props.record.id, diff)
    emit('saved')
    emit('update:open', false)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail ?? '保存失败'
  } finally {
    saving.value = false
  }
}
</script>
```

**实现时确认** `UiDialog` 的 props/emits（读 `frontend-vite/src/components/ui/UiDialog.vue`）。若它的双向绑定是 `v-model:visible` 而不是 `open`，按实际签名改，并同步改测试里的用法 —— 但**不要**改 `UiDialog` 本身。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/recordEditDialog.submit.test.ts`
Expected: PASS（4 passed）

- [ ] **Step 5: lint + type-check + 提交**

Run: `cd frontend-vite && npm run lint && npm run type-check`
Expected: 均无错误

```bash
git add frontend-vite/src/views/production/components/RecordEditDialog.vue frontend-vite/src/test/recordEditDialog.submit.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): 新增生产记录编辑弹窗

只提交改动过的字段；数量为 0 时拒绝提交。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 11: 重写 ProductionView（编排层）并删掉旧面板

**Files:**
- Modify: `frontend-vite/src/views/production/ProductionView.vue`（整体重写）
- Modify: `frontend-vite/src/views/production/components/ProductionToolbar.vue`（去掉日报/月报 Tab，加"明细"按钮）
- Rename: `components/ProductionEntryDrawer.vue` → `components/ProductionEntryDialog.vue`（它实现的是居中模态，名实不符）
- Delete: `components/ProductionDailyPanel.vue`、`components/ProductionMonthlyPanel.vue`、`components/KpiCard.vue`、`composables/useProductionCharts.ts`
- Test: `frontend-vite/src/test/productionView.cockpit.test.ts`

**Interfaces:**
- Consumes: 前面所有任务产出的组件与 composable；`dailyProductionApi.dailySummary / monthlySummary`；`useProductionTrend`（Task 4）；`useProductionRecords`（Task 8）
- Produces: 无（这是编排层，位于调用链顶端）

- [ ] **Step 1: 写失败的测试**

创建 `frontend-vite/src/test/productionView.cockpit.test.ts`：

```ts
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('@/api/production', () => ({
  dailyProductionApi: {
    dailySummary: vi.fn().mockResolvedValue({
      date: '2026-09-29', departments: [], overall_quantity: 0, overall_value: 0, overall_sku_count: 0,
    }),
    monthlySummary: vi.fn().mockResolvedValue({
      year: 2026, month: 9, daily_data: [], monthly_departments: [],
      monthly_total_quantity: 0, monthly_total_value: 0,
    }),
    trend: vi.fn().mockResolvedValue({
      success: true, start_date: '2026-09-01', end_date: '2026-09-30', departments: [], days: [],
    }),
    records: vi.fn().mockResolvedValue({
      success: true, data: [], total: 0, page: 1, per_page: 50, pages: 0, stats: null,
    }),
    deleteRecord: vi.fn(),
  },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import ProductionView from '@/views/production/ProductionView.vue'

/**
 * 本测试只验**编排**：四个区块是否就位、下钻是否真的驱动抽屉。
 * 因此把四个区块组件与两个弹窗都 stub 掉 —— 它们是 PrimeVue 重组件
 * （Drawer / DataTable / DatePicker），真挂载需要完整插件，且与本测试的断言无关；
 * 它们各自的渲染由前面任务自己的测试覆盖。
 * 注意：必须提供 QueryClient —— ProductionView 用了 @tanstack/vue-query。
 */
function mountView() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ProductionView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs: {
        CockpitKpiRow: { template: '<div data-test="cockpit-kpi" />' },
        ProductionTrendPanel: { template: '<div data-test="cockpit-trend" />' },
        DeptRankPanel: { template: '<div data-test="cockpit-rank" />' },
        DeptDrillCards: { template: '<div data-test="cockpit-dept-cards" />' },
        RecordDrawer: { template: '<div data-test="record-drawer" />' },
        RecordEditDialog: { template: '<div />' },
        ProductionEntryDialog: { template: '<div />' },
        teleport: true,
      },
    },
  })
}

describe('ProductionView（驾驶舱编排）', () => {
  it('渲染四个区块：KPI 条、趋势面板、部门排行、部门下钻卡', () => {
    const wrapper = mountView()

    expect(wrapper.find('[data-test="cockpit-kpi"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="cockpit-trend"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="cockpit-rank"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="cockpit-dept-cards"]').exists()).toBe(true)
  })

  it('不再渲染日报/月报 Tab', () => {
    const wrapper = mountView()

    expect(wrapper.text()).not.toContain('月报')
  })

  it('工具栏有明细入口与录入入口', () => {
    const wrapper = mountView()

    expect(wrapper.find('[data-test="open-records"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="open-entry"]').exists()).toBe(true)
  })

  it('点部门卡会打开抽屉并预置该部门筛选', async () => {
    const wrapper = mountView()

    // 部门卡在数据加载后才有内容；这里直接调用编排层暴露的 drill 处理
    await (wrapper.vm as unknown as { openRecordsFor: (d: string) => void }).openRecordsFor('filling')

    expect((wrapper.vm as unknown as { recordsOpen: boolean }).recordsOpen).toBe(true)
    expect((wrapper.vm as unknown as { recordsFilters: { department: string } }).recordsFilters.department).toBe('filling')
  })
})
```

**注意**：上面第 4 个用例依赖编排层通过 `defineExpose` 暴露 `openRecordsFor`、`recordsOpen`、`recordsFilters` 三个名字。这是刻意的：部门卡→抽屉的联动是本次重构的核心交互，值得一个直接断言，而不是靠"点了某个按钮再找某个 DOM"绕。**在 `ProductionView.vue` 里用 `defineExpose({ openRecordsFor, recordsOpen, recordsFilters })` 暴露它们。**

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend-vite && npx vitest run src/test/productionView.cockpit.test.ts`
Expected: FAIL —— 当前 `ProductionView.vue` 渲染的是日报/月报 Tab，四个 `data-test` 都不存在

- [ ] **Step 3: 改工具栏**

把 `frontend-vite/src/views/production/components/ProductionToolbar.vue` 重写为（去掉 `viewTab` 相关的 Tab 与 props，加"明细"按钮）：

```vue
<template>
  <header class="flex shrink-0 items-center gap-3 border-b border-border-light bg-surface-card px-6 py-3">
    <div class="flex items-center gap-1.5">
      <button class="flex h-8 w-8 items-center justify-center rounded-lg border border-border-light" aria-label="前一天" @click="emit('prev-day')">
        <FontAwesomeIcon icon="chevron-left" aria-hidden="true" />
      </button>
      <input
        :value="date"
        type="date"
        class="rounded-lg border border-border-light px-2.5 py-1.5 text-sm font-semibold tabular-nums"
        aria-label="日期选择"
        @input="emit('update:date', ($event.target as HTMLInputElement).value)"
      />
      <button class="flex h-8 w-8 items-center justify-center rounded-lg border border-border-light" aria-label="后一天" @click="emit('next-day')">
        <FontAwesomeIcon icon="chevron-right" aria-hidden="true" />
      </button>
      <button class="rounded-lg border border-primary-200 bg-primary-50 px-3 py-1.5 text-xs font-bold text-primary-700" @click="emit('today')">今天</button>
    </div>

    <span class="flex-1" />

    <button data-test="open-entry" class="rounded-lg bg-primary-600 px-3.5 py-2 text-xs font-bold text-white" @click="emit('open-entry')">
      <FontAwesomeIcon icon="plus" class="mr-1" aria-hidden="true" /> 录入
    </button>
    <button class="rounded-lg border border-border-light px-3.5 py-2 text-xs font-semibold" @click="emit('export')">导出</button>
    <button data-test="open-records" class="rounded-lg border border-border-light px-3.5 py-2 text-xs font-semibold" @click="emit('open-records')">明细</button>
  </header>
</template>

<script setup lang="ts">
defineProps<{ date: string }>()

const emit = defineEmits<{
  'update:date': [value: string]
  'prev-day': []
  'next-day': []
  today: []
  'open-entry': []
  'open-records': []
  export: []
}>()
</script>
```

- [ ] **Step 4: 重命名录入弹窗并更新引用**

```bash
command git mv frontend-vite/src/views/production/components/ProductionEntryDrawer.vue frontend-vite/src/views/production/components/ProductionEntryDialog.vue
command grep -rn "ProductionEntryDrawer" frontend-vite/src/ || echo "无残留引用"
```

若有残留引用（在旧的 `ProductionView.vue` 里），第 5 步重写 `ProductionView.vue` 时一并改为 `ProductionEntryDialog`。同时把该组件模板里的 `pr-entry-overlay` 等类名保留不动（本次只改名，不改它的内部样式 —— 它的视觉在 Task 12 的浏览器核对里确认）。

- [ ] **Step 5: 重写 ProductionView**

把 `frontend-vite/src/views/production/ProductionView.vue` 整体重写为编排层。**目标 ≤ 400 行，理想 250 行以内**：

```vue
<template>
  <div class="page-card page-card-main m-0 h-full">
    <ProductionToolbar
      v-model:date="selectedDate"
      @prev-day="goPrevDay"
      @next-day="goNextDay"
      @today="goToday"
      @open-entry="entryOpen = true"
      @open-records="openRecordsFor('')"
      @export="handleExport"
    />

    <div class="page-card-body flex flex-col gap-3">
      <CockpitKpiRow
        data-test="cockpit-kpi"
        :today="todaySummary"
        :yesterday="yesterdaySummary"
        :monthly="monthlySummary"
        :previous-month="previousMonthSummary"
      />

      <div class="grid min-h-0 grid-cols-1 gap-3 xl:grid-cols-[2fr_1fr]">
        <ProductionTrendPanel data-test="cockpit-trend" :trend="trendData" :loading="trendLoading" />
        <DeptRankPanel data-test="cockpit-rank" :departments="monthlySummary?.monthly_departments ?? []" :loading="monthlyLoading" />
      </div>

      <DeptDrillCards
        data-test="cockpit-dept-cards"
        :departments="todaySummary?.departments ?? []"
        :loading="dailyLoading"
        @drill="openRecordsFor"
      />
    </div>

    <RecordDrawer
      v-model:open="recordsOpen"
      :filters="recordsFilters"
      :records="recordsQuery.data.value?.data ?? []"
      :total="recordsQuery.data.value?.total ?? 0"
      :stats="recordsQuery.data.value?.stats ?? null"
      :loading="recordsQuery.isFetching.value"
      :departments="visibleDepartments"
      :created-by-options="createdByOptions"
      @update:filters="recordsFilters = $event"
      @search="onRecordsSearch"
      @edit="openEdit"
      @confirm-delete="onConfirmDelete"
    />

    <RecordEditDialog v-model:open="editOpen" :record="editingRecord" @saved="onRecordSaved" />

    <ProductionEntryDialog v-model:open="entryOpen" v-model:selected-date="selectedDate" />

    <Transition name="pr-toast">
      <div v-if="exportStatus.show" :class="['pr-export-toast', exportStatus.type]">
        <span>{{ exportStatus.message }}</span>
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { dailyProductionApi } from '@/api/production'
import { showToast } from '@/composables/useToast'
import type { DailyProductionRecord, DailySummary, MonthlySummary } from '@/types'
import ProductionToolbar from './components/ProductionToolbar.vue'
import CockpitKpiRow from './components/CockpitKpiRow.vue'
import ProductionTrendPanel from './components/ProductionTrendPanel.vue'
import DeptRankPanel from './components/DeptRankPanel.vue'
import DeptDrillCards from './components/DeptDrillCards.vue'
import RecordDrawer from './components/RecordDrawer.vue'
import RecordEditDialog from './components/RecordEditDialog.vue'
import ProductionEntryDialog from './components/ProductionEntryDialog.vue'
import { useProductionTrend } from './composables/useProductionTrend'
import { useProductionRecords } from './composables/useProductionRecords'
import { defaultRecordFilters, type RecordFilters } from './composables/recordFilters'
import { toLocalDate } from './composables/productionDate'

const TREND_DAYS = ref(30)

const selectedDate = ref(toLocalDate(new Date()))
const entryOpen = ref(false)
const editOpen = ref(false)
const editingRecord = ref<DailyProductionRecord | null>(null)
const recordsOpen = ref(false)
const recordsFilters = ref<RecordFilters>(defaultRecordFilters())

function goPrevDay() {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  d.setDate(d.getDate() - 1)
  selectedDate.value = toLocalDate(d)
}
function goNextDay() {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  d.setDate(d.getDate() + 1)
  selectedDate.value = toLocalDate(d)
}
function goToday() {
  selectedDate.value = toLocalDate(new Date())
}

// ===== 三个数据源 =====
const { data: dailyData, isFetching: dailyLoading } = useQuery({
  queryKey: computed(() => ['daily-production-daily-summary', selectedDate.value]),
  queryFn: () => dailyProductionApi.dailySummary(selectedDate.value),
  staleTime: 30_000,
})
const todaySummary = computed<DailySummary | null>(() => dailyData.value ?? null)

const yesterdayDate = computed(() => {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  d.setDate(d.getDate() - 1)
  return toLocalDate(d)
})
const { data: yesterdayData } = useQuery({
  queryKey: computed(() => ['daily-production-daily-summary', yesterdayDate.value]),
  queryFn: () => dailyProductionApi.dailySummary(yesterdayDate.value),
  staleTime: 30_000,
})
const yesterdaySummary = computed<DailySummary | null>(() => yesterdayData.value ?? null)

const { data: monthlyData, isFetching: monthlyLoading } = useQuery({
  queryKey: computed(() => [
    'daily-production-monthly-summary',
    new Date(`${selectedDate.value}T00:00:00`).getFullYear(),
    new Date(`${selectedDate.value}T00:00:00`).getMonth() + 1,
  ]),
  queryFn: () =>
    dailyProductionApi.monthlySummary({
      year: new Date(`${selectedDate.value}T00:00:00`).getFullYear(),
      month: new Date(`${selectedDate.value}T00:00:00`).getMonth() + 1,
    }),
  staleTime: 60_000,
})
const monthlySummary = computed<MonthlySummary | null>(() => monthlyData.value ?? null)

/** 上月汇总：只用于 KPI 条的"日均较上月"。跨年时月份回绕到 12 月、年份减一。 */
const previousMonthParts = computed(() => {
  const d = new Date(`${selectedDate.value}T00:00:00`)
  const year = d.getMonth() === 0 ? d.getFullYear() - 1 : d.getFullYear()
  const month = d.getMonth() === 0 ? 12 : d.getMonth()
  return { year, month }
})
const { data: previousMonthData } = useQuery({
  queryKey: computed(() => ['daily-production-monthly-summary', previousMonthParts.value.year, previousMonthParts.value.month]),
  queryFn: () => dailyProductionApi.monthlySummary(previousMonthParts.value),
  staleTime: 60_000,
})
const previousMonthSummary = computed<MonthlySummary | null>(() => previousMonthData.value ?? null)

const { trendQuery } = useProductionTrend(TREND_DAYS)
const trendData = computed(() => trendQuery.data.value ?? null)
const trendLoading = computed(() => trendQuery.isFetching.value)

const { recordsQuery, removeRecord } = useProductionRecords(recordsFilters)

/** 可见部门：优先用今日汇总返回的（它已按权限收窄），否则回落到趋势返回的 */
const visibleDepartments = computed(() => {
  const fromDaily = todaySummary.value?.departments.map((d) => d.department)
  if (fromDaily?.length) return fromDaily
  return trendData.value?.departments ?? []
})

/** 录单人下拉的可选值：从当前页记录里去重（后端没有独立的录单人字典接口） */
const createdByOptions = computed(() => {
  const names = new Set<string>()
  for (const r of recordsQuery.data.value?.data ?? []) {
    if (r.created_by) names.add(r.created_by)
  }
  return [...names].sort().map((n) => ({ label: n, value: n }))
})

function openRecordsFor(department: string) {
  recordsFilters.value = { ...recordsFilters.value, department, page: 1 }
  recordsOpen.value = true
}

function onRecordsSearch() {
  recordsFilters.value = { ...recordsFilters.value, page: 1 }
}

function openEdit(record: DailyProductionRecord) {
  editingRecord.value = record
  editOpen.value = true
}

function onRecordSaved() {
  showToast('保存成功', 'success')
}

async function onConfirmDelete(id: number) {
  try {
    await removeRecord.mutateAsync(id)
    showToast('已删除', 'success')
  } catch {
    showToast('删除失败', 'error')
  }
}

// ===== 导出 =====
const exportStatus = reactive({ show: false, message: '', type: 'info' })
let exportTimer: ReturnType<typeof setTimeout> | undefined

async function handleExport() {
  exportStatus.show = true
  exportStatus.type = 'info'
  exportStatus.message = '正在导出报表…'
  try {
    await dailyProductionApi.export({ start_date: selectedDate.value, end_date: selectedDate.value })
    exportStatus.type = 'success'
    exportStatus.message = '导出成功'
  } catch {
    exportStatus.type = 'error'
    exportStatus.message = '导出失败，请稍后重试'
  }
  exportTimer = setTimeout(() => {
    exportStatus.show = false
  }, 3000)
}

defineExpose({ openRecordsFor, recordsOpen, recordsFilters })
</script>

<style scoped>
.pr-export-toast {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 120;
  padding: 10px 18px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
}
.pr-export-toast.info { background: var(--color-primary-50); color: var(--color-primary-700); }
.pr-export-toast.success { background: #f0fdf4; color: #15803d; }
.pr-export-toast.error { background: #fef2f2; color: #dc2626; }
.pr-toast-enter-active, .pr-toast-leave-active { transition: opacity 0.3s ease; }
.pr-toast-enter-from, .pr-toast-leave-to { opacity: 0; }
</style>
```

**注意**：`exportTimer` 目前没在卸载时清理。若 `npm run lint` 或评审指出这一点，加 `onUnmounted(() => clearTimeout(exportTimer))` —— 原实现有一个 `_timers` 数组做同样的事。

- [ ] **Step 6: 删除旧面板**

```bash
command git rm frontend-vite/src/views/production/components/ProductionDailyPanel.vue
command git rm frontend-vite/src/views/production/components/ProductionMonthlyPanel.vue
command git rm frontend-vite/src/views/production/components/KpiCard.vue
command git rm frontend-vite/src/views/production/composables/useProductionCharts.ts
command grep -rn "ProductionDailyPanel\|ProductionMonthlyPanel\|KpiCard\|useProductionCharts" frontend-vite/src/ || echo "无残留引用 ✔"
```

若有残留引用，逐一改到新组件；**不允许**为了通过编译而保留死文件。

- [ ] **Step 7: 跑测试确认通过**

Run: `cd frontend-vite && npx vitest run src/test/productionView.cockpit.test.ts`
Expected: PASS（4 passed）

- [ ] **Step 8: 全量前端测试 + 门禁**

Run:
```bash
cd frontend-vite && npm run lint && npm run type-check && npm test
cd .. && python scripts/quality_gate.py
```
Expected: 全部通过。**特别确认 `ProductionView.vue` 与 `RecordDrawer.vue` 都在 400 行以内**（`quality_gate.py` 会报）。

- [ ] **Step 9: 提交**

```bash
git add frontend-vite/src/views/production/ frontend-vite/src/test/productionView.cockpit.test.ts
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息：

```
feat(production): 生产页重构为一屏驾驶舱 + 明细抽屉

替换日报/月报双 Tab；删除 ProductionDailyPanel / ProductionMonthlyPanel /
KpiCard / useProductionCharts（其中两个面板曾有约 90 行逐字重复的 CSS）；
ProductionEntryDrawer 改名为 ProductionEntryDialog（它实现的是居中模态）。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```

）

---

### Task 12: 收尾 —— 浏览器核对与视觉统一

**Files:**
- Modify: 视核对结果而定（本任务不预设改动清单）

- [ ] **Step 1: 起服务并在浏览器里核对**

**先确认端口**：本机 `:3000` 可能正被**生产前端**（nginx 托管 dist）占用，而 `npm run dev` 默认也想用 3000。**不要**为了跑 dev 去停生产服务。先探测：

```bash
command curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/ || echo "3000 未响应"
```

若 3000 已在服务，改用别的端口起 dev：

```bash
cd frontend-vite && npm run dev -- --port 5199
```

（用 5199 打开核对，不要动 3000 上正在跑的东西。）

按规格 §8.3 逐条核对（**这是本计划唯一能验证"功能正确"而不是"代码正确"的步骤**）：

- [ ] 打开 `/production`，一屏之内看到：KPI 条（今日产量/产值/本月累计/日均）、近 30 日趋势、本月部门排行、三张部门下钻卡
- [ ] **不需要滚动**就能看完以上四块（1440×900 与 1920×1080 各看一次）
- [ ] 点「充棉部」下钻卡 → 抽屉打开且部门筛选已预置为充棉部
- [ ] 抽屉里：切「本周」→ 记录范围变化；切「自定义」并选一个跨月区间 → 仍能出结果（验证跨月）
- [ ] 抽屉里搜一个产品名的片段 → 结果被筛掉（验证 Task 7 的 keyword 真的生效）
- [ ] 抽屉里「改」一条记录 → 弹窗打开、改数量 → 保存 → 抽屉里的数字随之变化
- [ ] 抽屉里「删」一条记录 → 确认框显示产品名/数量/日期/部门 → 确认 → 该行消失、合计随之下降
- [ ] 点「导出」→ 下载的 xlsx 内容与当前所选日期一致
- [ ] 点「录入」→ 录入一条 → 抽屉里能查到它
- [ ] 缩小窗口到 1366×768：四个区块仍可用（趋势图变矮、部门卡改单列）
- [ ] 浏览器控制台无报错

- [ ] **Step 2: 视觉统一核对**

- [ ] 全页搜索硬编码色值：`command grep -rn "#eff6ff\|#1e40af\|#f0fdf4\|#fffbeb" frontend-vite/src/views/production/` → 应**无输出**（除 `trendChartOption.ts` 与 `kpiDelta.ts` 里作为部门色/图表色的那几处常量，那些是刻意的唯一来源）
- [ ] 部门色只出现在 `trendChartOption.ts` 一处定义
- [ ] 没有残留的日报/月报 Tab 文案

- [ ] **Step 3: 记录核对结果**

把上面每一项的实际结果写进报告文件（哪一项通过、哪一项发现问题、发现的问题如何处置）。**不要**只写"已验证"。

- [ ] **Step 4: 若核对发现问题，就地修复并补测试**

按问题的性质回到对应任务补测试，而不是只在浏览器里改代码 —— 浏览器核对发现的问题正是"测试没覆盖到的行为"，值得留下一条回归测试。

- [ ] **Step 5: 提交**

```bash
git add <本步实际改动的路径>
git commit -F "C:/Users/Administrator/AppData/Local/Temp/erp_commit_msg.txt"
```

（提交信息按实际改动写，结尾仍是 `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`。）

---

## 完成标准

Plan B1 完成的判定（全部满足）：

1. 12 个任务的测试全部通过；`npm run type-check`、`npm run lint`、`npm test`、`python scripts/quality_gate.py` 四道全绿。
2. 每个新建的 `.vue` 都在 400 行以内（含 `ProductionView.vue` 与 `RecordDrawer.vue`）。
3. 打开 `/production` 一屏可见四个区块，无需滚动（1440×900 与 1920×1080）。
4. 部门下钻、抽屉筛选（含跨月区间与关键词）、编辑、删除、导出、录入六条链路在浏览器里逐条走通。
5. 硬编码色值清零（部门色/图表色除外，且只在 `trendChartOption.ts` 定义一处）。
6. 旧的日报/月报面板、`KpiCard`、`useProductionCharts` 已删除且无残留引用。

**本计划不含**：移动端（`src/mobile/views/production/**`）—— 见 Plan B2。

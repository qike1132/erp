<template>
  <div class="sp-body">
    <div v-if="isLoading" class="sp-empty"><UiSpinner /></div>
    <div v-else-if="isError" class="sp-empty">
      <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />加载失败
      <button class="sp-retry-btn" aria-label="重试" @click="emit('refetch')">重试</button>
    </div>
    <div v-else-if="!rows.length" class="sp-empty">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" />本月暂无出货计划
    </div>
    <template v-else>
      <div v-if="isFetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>

      <div class="sp-layout">
        <!-- 左：月历热力 + 风险条 + 客户 chips + SKU 月度统计（原「月度汇总」Tab 并入此处） -->
        <div class="sp-panel">
          <div class="sp-panel-head">
            <span>{{ y }}年{{ pad(m) }}月 · 排产月历</span>
            <span class="sp-inline-legend">
              <span><i class="lg-r" />逾期</span>
              <span><i class="lg-a" />临期≤3天</span>
              <span><i class="lg-g" />已完成</span>
            </span>
          </div>
          <PlanMonthGrid
            :y="y"
            :m="m"
            :rows="rows"
            :sel="sel"
            :searching="isSearching"
            :matched-dates="matchedDates"
            :day-meta="dayMeta"
            :cust-colors="custColors"
            @select="selectDate"
          />
          <div v-if="isSearching" class="sp-search-hint">搜索命中 {{ matchedDates.size }} 个排产日</div>

          <!-- 风险从右栏清单压成一行条：点条目即跳到那天，明细看格子标记与当日明细 -->
          <div v-if="riskItems.length" class="sp-risk-strip">
            <span class="sp-risk-strip-l">风险</span>
            <button
              v-for="it in riskItems"
              :key="it.date"
              :class="['sp-risk-chip', it.kind === 'overdue' ? 'is-r' : 'is-a']"
              :aria-label="`${short(it.date)} ${it.lbl}，${it.qty}件，查看当日明细`"
              @click="selectDate(it.date)"
            >
              <i aria-hidden="true" />
              <span class="num">{{ short(it.date) }}</span> {{ it.lbl }}
              <b class="num">{{ fmt(it.qty) }}件</b>
            </button>
          </div>
          <div v-else class="sp-risk-strip">
            <span class="sp-risk-strip-l">风险</span>
            <span class="sp-risk-ok">本月无逾期与临期</span>
          </div>

          <!-- 月度汇总区（客户 chips + SKU 月度统计）拆为子组件：单 SFC ≤400 行门禁 -->
          <PurchasePlanSummarySection
            :customers="customers"
            :cust-filter="custFilter"
            :cust-colors="custColors"
            :sorted-sku-list="sortedSkuList"
            :paginated-sku-list="paginatedSkuList"
            :sku-page="skuPage"
            :sku-total-pages="skuTotalPages"
            :sku-sort-field="skuSortField"
            :sku-sort-dir="skuSortDir"
            @update:cust-filter="emit('update:custFilter', $event)"
            @update:sku-page="emit('update:skuPage', $event)"
            @toggle-sku-sort="emit('toggle-sku-sort', $event)"
            @open-sku-detail="emit('open-sku-detail', $event)"
            @export-sku="emit('export-sku')"
          />
        </div>

        <!-- 右：当日明细（默认选中今天，见 useDefaultTodaySelection） -->
        <div class="sp-rail">
          <div class="sp-panel sp-rail-panel">
            <PlanDayDetail
              v-if="selRow"
              :title="selTitle"
              :groups="selGroups"
              :total-qty="selRow.totalQty"
              :customer-count="selRow.customerCount"
              :product-count="selProductCount"
              :cust-colors="custColors"
            />
            <div v-else class="sp-rail-empty">
              <p>点击月历任一日期，查看当日「客户 × SKU × 数量」明细</p>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
// 方案B（2026-11-28 owner 拍板）合并后的单视图主体：
// 左列 = 排产月历 + 风险条 + 本月客户 chips + SKU 月度统计；右列 = 当日明细主区。
// 本组件只做组装与派生：数据全部来自已有的 rows / skuDateIndex / customers，不发新请求。
import { computed } from 'vue'
import PlanMonthGrid from './PlanMonthGrid.vue'
import PlanDayDetail from './PlanDayDetail.vue'
import PurchasePlanSummarySection from './PurchasePlanSummarySection.vue'
import type { CustSumItem, DayCellMeta, RiskItem, Row, SkuDateItem, SkuRow, PlanDayCustomerGroup } from './types'
import { formatNumber as fmt } from '@/utils/format' // L-15（2026-11-21 审计）：删除 8 处各自为政的本地 fmt，统一千分位口径

const props = defineProps<{
  y: number
  m: number
  isLoading: boolean
  isError: boolean
  isFetching: boolean
  rows: Row[]
  filtered: Row[]
  skuDateIndex: Record<string, SkuDateItem[]>
  sel: string
  /** 当月客户汇总（已按工厂收敛），供 chips 与配色排序 */
  customers: CustSumItem[]
  riskItems: RiskItem[]
  custFilter: string
  sortedSkuList: SkuRow[]
  paginatedSkuList: SkuRow[]
  skuPage: number
  skuTotalPages: number
  skuSortField: string
  skuSortDir: 'asc' | 'desc'
}>()

const emit = defineEmits<{
  'update:sel': [value: string]
  'update:custFilter': [value: string]
  'update:skuPage': [value: number]
  'toggle-sku-sort': [field: string]
  'open-sku-detail': [payload: { barcode: string; name: string; customer: string }]
  'export-sku': []
  refetch: []
}>()

const pad = (n: number) => String(n).padStart(2, '0')

const matchedDates = computed(() => new Set(props.filtered.map(r => r.date)))
const isSearching = computed(() => props.filtered.length > 0 && props.filtered.length < props.rows.length)

// sku_date_index 的键为「客户|产品」，此处按日期反转成 日期 → 明细行 的索引
const itemsByDate = computed(() => {
  const map = new Map<string, { customer: string; product: string; qty: number; status: string; factory?: string }[]>()
  for (const [key, entries] of Object.entries(props.skuDateIndex ?? {})) {
    const sep = key.indexOf('|')
    const customer = sep < 0 ? key : key.slice(0, sep)
    const product = sep < 0 ? '' : key.slice(sep + 1)
    for (const e of entries) {
      const item = { customer, product, qty: e.qty, status: e.status, factory: e.factory }
      const list = map.get(e.date)
      if (list) list.push(item)
      else map.set(e.date, [item])
    }
  }
  return map
})

/**
 * 按客户分组：同一客户在该日的多条产品明细归到一组，组内按数量降序。
 * 不做「产品行数预算」截断 —— 截断是卡片时代的产物，明细栏本来就该滚动展示全部。
 */
const groupsByDate = computed(() => {
  const out = new Map<string, PlanDayCustomerGroup[]>()
  for (const [date, items] of itemsByDate.value) {
    const byCustomer = new Map<string, PlanDayCustomerGroup>()
    for (const it of items) {
      let g = byCustomer.get(it.customer)
      if (!g) {
        g = { customer: it.customer, qty: 0, products: [] }
        byCustomer.set(it.customer, g)
      }
      g.qty += it.qty
      g.products.push({ product: it.product, qty: it.qty, status: it.status, factory: it.factory })
    }
    const list = [...byCustomer.values()]
    for (const g of list) g.products.sort((a, b) => b.qty - a.qty)
    list.sort((a, b) => b.qty - a.qty)
    out.set(date, list)
  }
  return out
})

/** 月历格子的当日元信息：客户数量分布（降序）+ 去重 SKU 数 */
const dayMeta = computed<Record<string, DayCellMeta>>(() => {
  const out: Record<string, DayCellMeta> = {}
  for (const [date, groups] of groupsByDate.value) {
    const skuSet = new Set<string>()
    for (const g of groups) for (const p of g.products) skuSet.add(p.product)
    out[date] = {
      custs: groups.map(g => ({ name: g.customer, qty: g.qty })),
      skuN: skuSet.size,
    }
  }
  return out
})

/** 客户 → 展示色：按月度计划量降序分配色板，月历/明细/chips 三处同源 */
const CUST_PALETTE = [
  'var(--color-primary-500, #5b8def)',
  'var(--color-success-500, #28c76f)',
  'var(--color-warning-500, #ff9f43)',
  'var(--color-purple-500, #8b5cf6)',
  'var(--color-cyan-500, #06b6d4)',
  'var(--color-danger-500, #ea5455)',
]
const FALLBACK_COLOR = 'var(--color-slate-400, #94a3b8)'
const custColors = computed<Record<string, string>>(() => {
  const ordered = [...props.customers].sort((a, b) => b.plan_qty - a.plan_qty)
  const out: Record<string, string> = {}
  ordered.forEach((c, i) => { out[c.customer_name] = CUST_PALETTE[i % CUST_PALETTE.length] ?? FALLBACK_COLOR })
  return out
})

const selRow = computed<Row | null>(
  () => props.rows.find(r => r.date === props.sel) ?? null,
)

const selGroups = computed<PlanDayCustomerGroup[]>(
  () => groupsByDate.value.get(props.sel) ?? [],
)

const selProductCount = computed(
  () => selGroups.value.reduce((n, g) => n + g.products.length, 0),
)

const selTitle = computed(() => {
  const r = selRow.value
  if (!r) return ''
  return `${Number(r.date.slice(5, 7))}月${r.date.slice(8, 10)}日 周${r._weekday}`
})

/** 2026-09-08 → 09/08 */
function short(date: string): string {
  return date.slice(5).replace('-', '/')
}

function selectDate(date: string): void {
  emit('update:sel', props.sel === date ? '' : date)
}
</script>

<style scoped lang="scss">
@use '../purchase-plan-common.scss' as *;

.sp-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 24px 22px;
}

.sp-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 430px;
  gap: 16px;
  align-items: start;
}

/* 侧栏在窄屏下沉；断点取 1180px —— 再窄下去 7 列格子不足 120px，
   客户数/SKU数这一行会被挤成省略号，月历就只剩日期可看。 */
@media (max-width: 1180px) {
  .sp-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* 图例只此一处（状态标签在格子标记上不再重复出现） */
.sp-inline-legend {
  display: flex;
  gap: 12px;
  font-size: var(--fs-caption);
  font-weight: 500;
  color: var(--color-text-muted, #8c96ad);
}

.sp-inline-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.sp-inline-legend i {
  width: 3px;
  height: 11px;
  border-radius: 2px;
}

.lg-r { background: var(--color-danger-500); }
.lg-a { background: var(--color-warning-500); }
.lg-g { background: var(--color-success-500); }

.sp-search-hint {
  padding: 0 18px 10px;
  font-size: var(--fs-caption);
  color: var(--color-primary-600);
}

/* 风险条：月历下方一行 chips，点条目跳当天 */
.sp-risk-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 18px 12px;
}

.sp-risk-strip-l {
  font-size: var(--fs-caption);
  font-weight: 700;
  color: var(--color-text-muted);
}

.sp-risk-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 0;
  background: white;
  font-family: inherit;
  font-size: var(--fs-caption);
  font-weight: 600;
  color: var(--color-text-secondary, #475569);
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.sp-risk-chip i {
  width: 7px;
  height: 7px;
}

.sp-risk-chip.is-r i { background: var(--color-danger-500); }
.sp-risk-chip.is-a i { background: var(--color-warning-500); }
.sp-risk-chip.is-r { border-color: var(--color-danger-200, #f5c2c2); color: var(--color-danger-700); }
.sp-risk-chip.is-a { border-color: var(--color-warning-200, #fdddc3); color: var(--color-warning-700); }

.sp-risk-chip:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
}

.sp-risk-chip:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

.sp-risk-ok {
  font-size: var(--fs-caption);
  font-weight: 600;
  color: var(--color-success-600);
}

.sp-rail-panel {
  min-height: 200px;
}

.sp-rail-empty {
  padding: 46px 20px;
  text-align: center;
  font-size: var(--fs-body-sm);
  color: var(--color-text-muted, #8c96ad);
}
</style>

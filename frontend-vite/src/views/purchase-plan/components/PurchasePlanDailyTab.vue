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
        <!-- 左：整月排产日历 -->
        <div class="sp-panel">
          <div class="sp-panel-head">
            <span>{{ y }}年{{ pad(m) }}月 · 排产日历{{ factory === 'all' ? '' : '（仅' + factory + '）' }}</span>
            <span class="sp-inline-legend">
              <span><i class="lg-r" />逾期</span>
              <span><i class="lg-a" />临期≤3天</span>
              <span><i class="lg-g" />已完成</span>
              <!-- 工厂图例随当月实际出现的工厂走（含「未标注」），与格内构成条颜色一一对应 -->
              <template v-if="factory === 'all'">
                <span v-for="f in rowFactories" :key="f"><i :class="`lg-${factoryTone(f)}`" />{{ f }}</span>
              </template>
            </span>
          </div>
          <PlanMonthGrid
            :y="y"
            :m="m"
            :rows="rows"
            :sel="sel"
            :factory="factory"
            :searching="isSearching"
            :matched-dates="matchedDates"
            @select="selectDate"
          />
          <div v-if="isSearching" class="sp-search-hint">搜索命中 {{ matchedDates.size }} 个排产日</div>
        </div>

        <!-- 右：未选日 → 风险清单；选中日 → 该日完整明细 -->
        <div class="sp-rail">
          <div class="sp-panel sp-rail-panel">
            <div class="sp-panel-head">
              <span>{{ selRow ? '当日明细' : '风险清单' }}</span>
              <button v-if="sel" class="sp-rail-clear" @click="selectDate(sel)">返回风险清单</button>
              <span v-else-if="riskItems.length" class="xs">{{ riskItems.length }} 天待处理</span>
            </div>

            <PlanDayDetail
              v-if="selRow"
              :title="selTitle"
              :groups="selGroups"
              :total-qty="selRow.totalQty"
              :customer-count="selRow.customerCount"
              :product-count="selProductCount"
              :factory="factory"
            />
            <PlanRiskList v-else :items="riskItems" @select="selectDate" />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
// 「排产日历」Tab —— 左侧整月月历 + 右侧栏双态（风险清单 / 当日明细）。
// 本组件只做组装与派生：数据全部来自已有的 rows / skuDateIndex，不发新请求。
import { computed } from 'vue'
import PlanMonthGrid from './PlanMonthGrid.vue'
import PlanDayDetail from './PlanDayDetail.vue'
import PlanRiskList from './PlanRiskList.vue'
import { daysFromToday, startOfToday } from './dayStatus'
import { orderFactories, factoryTone } from './factoryMeta'
import type { Row, SkuDateItem, PlanDayCustomerGroup, RiskItem } from './types'

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
  /** 当前工厂筛选（'all' 或具体工厂名）；'all' 时日历格内叠加工厂构成条 */
  factory: string
}>()

const emit = defineEmits<{
  'update:sel': [value: string]
  refetch: []
}>()

const TODAY_MS = startOfToday()

const pad = (n: number) => String(n).padStart(2, '0')

const matchedDates = computed(() => new Set(props.filtered.map(r => r.date)))
const isSearching = computed(() => props.filtered.length > 0 && props.filtered.length < props.rows.length)

/** 当月实际出现过的工厂（按固定顺序），用于日历图例——含「未标注」，与格内构成条一一对应 */
const rowFactories = computed<string[]>(() => {
  const s = new Set<string>()
  for (const r of props.rows) for (const f of Object.keys(r.factories ?? {})) s.add(f)
  return orderFactories([...s])
})

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
 * 不再做「产品行数预算」截断 —— 截断是卡片时代的产物，右栏本来就该滚动展示全部。
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

// 风险条目：延期或临期(≤3天)且未完成
const riskItems = computed<RiskItem[]>(() => {
  const list: RiskItem[] = []
  for (const r of props.rows) {
    if (r._producedPct === 100 || r._pendingCount <= 0) continue
    const diff = daysFromToday(r.date, TODAY_MS)
    if (diff < 0) {
      list.push({ date: r.date, qty: r.totalQty, cust: r.customerNames[0] ?? '', kind: 'overdue', lbl: '延期 ' + Math.abs(diff) + '天' })
    } else if (diff <= 3) {
      list.push({ date: r.date, qty: r.totalQty, cust: r.customerNames[0] ?? '', kind: 'due', lbl: diff === 0 ? '今日出货' : '临期 ' + diff + '天' })
    }
  }
  list.sort((a, b) => daysFromToday(a.date, TODAY_MS) - daysFromToday(b.date, TODAY_MS))
  return list
})

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
  grid-template-columns: minmax(0, 1fr) 336px;
  gap: 16px;
  align-items: start;
}

/* 侧栏在窄屏下沉；断点取 1180px —— 再窄下去 7 列格子不足 120px，
   产品数/客户数这一行会被挤成省略号，月历就只剩日期可看。 */
@media (max-width: 1180px) {
  .sp-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

.sp-panel {
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-md, 14px);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.sp-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
}

.sp-panel-head .xs {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted, #8c96ad);
}

/* 图例只此一处（原卡片版的图例在面板底部另有一条，且状态标签在卡片上重复出现） */
.sp-inline-legend {
  display: flex;
  gap: 12px;
  font-size: 11px;
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
/* 工厂色档（与 factoryMeta.factoryTone 对应）：东莞主色 / 湖北紫 / 其余中性 */
.lg-dg { background: var(--color-primary-500, #5b8def); }
.lg-hb { background: var(--color-purple-500, #8b5cf6); }
.lg-other { background: var(--color-slate-300, #cbd5e1); }

.sp-search-hint {
  padding: 0 18px 14px;
  font-size: 12px;
  color: var(--color-primary-600);
}

.sp-rail-panel {
  min-height: 200px;
}

.sp-rail-clear {
  border: none;
  background: transparent;
  padding: 0;
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary-600);
  cursor: pointer;
}

.sp-rail-clear:hover {
  color: var(--color-primary-700);
  text-decoration: underline;
}
</style>

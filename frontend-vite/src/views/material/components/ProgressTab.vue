<template>
  <div class="mr-content">
    <div v-if="pIsFetching && progressOrderRows.length" class="mr-fetching-bar"><div class="mr-fetching-progress" /></div>

    <div class="mr-scroll">
      <!-- 本页异常筛选：把「找异常」从逐行扫视降为一次点击（作用域仍是当前页） -->
      <div v-if="progressOrderRows.length" class="mr-filterbar">
        <div class="mr-filters" role="group" aria-label="按异常筛选本页订单">
          <button
            v-for="f in FILTERS"
            :key="f.key"
            type="button"
            :class="['mr-filter', { 'is-active': filterKey === f.key }]"
            :aria-pressed="filterKey === f.key"
            @click="filterKey = f.key"
          >
            {{ f.label }}<span class="mr-filter-n">{{ filterCounts[f.key] }}</span>
          </button>
        </div>
        <span class="mr-filter-hint">本页 {{ progressOrderRows.length }} 单</span>
      </div>

      <!-- 首次加载：骨架屏（保留版面高度，避免表头跳动） -->
      <div v-if="showSkeleton" class="mr-orders" aria-hidden="true">
        <div v-for="i in 3" :key="i" class="mr-skel">
          <div class="mr-skel-head"><span /><span /><span /></div>
          <div class="mr-skel-row"><span /><span /><span /></div>
          <div class="mr-skel-row"><span /><span /><span /></div>
        </div>
      </div>

      <!-- 空态：无数据 / 搜索无命中 / 筛选无命中，三种口径分开说 -->
      <div v-else-if="!visibleRows.length" class="mr-empty">
        <FontAwesomeIcon :icon="emptyIcon" />
        <span>{{ emptyText }}</span>
      </div>

      <div v-else class="mr-orders">
        <OrderCard
          v-for="row in visibleRows"
          :key="row.orderNo"
          :row="row"
          @view-supplier="onViewSupplier"
        />
      </div>
    </div>

    <UiPagination
      v-if="pCount > 0 || pPages > 1"
      :current-page="pPage"
      :total-pages="Math.max(1, pPages)"
      :total-items="pCount > 0 ? pCount : undefined"
      :page-size="pPerPage"
      :page-size-options="[10, 20, 50, 100]"
      item-unit="条登记"
      @update:current-page="onPage"
      @update:page-size="onPageSize"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * ProgressTab.vue — 来料进度（订单卡片 · 供应商分组清单）
 *
 * 2026-11-08 改版：取消 7 列表格，改为「一单一卡 + 供应商分组清单」。
 *  · 层级：订单卡（身份/摘要/总进度）→ 供应商行（左轨状态色 + 状态词 + 进度条）
 *    → 物料行（缩进 + 共用列轨道）。三级靠缩进与左轨区分，不靠边框堆叠。
 *  · 关键数据前置：订单层给「供应商数 / 待收项数 / 逾期项数」；供应商层给
 *    「已到 x/y 项 + 进度%」；物料层给「已到 / 采购 单位 + 进度%」。数量聚合只在
 *    物料层出现——组内单位可能不同，不做跨单位求和。
 *  · 减少干扰：删除顶部图例条（每个状态都带文字，无需靠色块反查）、删除组头
 *    64px 迷你条（与物料条重复）、删除独立「总进度」列（并入订单头）。
 *  · 响应式：≥861px 三级列轨道对齐；≤860px 供应商/物料行降为两行网格；
 *    ≤520px 订单头三段纵排。窄屏不再依赖横向滚动。
 *  · 交互：供应商行默认展开（沿用 collapse 语义反转），整行可点 + 键盘可达；
 *    新增「全部 / 有逾期 / 未开始」本页筛选。
 */
import { computed, ref } from 'vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import type { ProgressOrderRow } from '../composables/useMaterialRegistrations'
import OrderCard from './OrderCard.vue'

const props = defineProps<{
  /** 搜索过滤后的行（父级持有搜索词） */
  filteredRows: ProgressOrderRow[]
  /** 未过滤的行（fetching 提示与空态判断用） */
  progressOrderRows: ProgressOrderRow[]
  pIsLoading: boolean
  pIsFetching: boolean
  pPerPage: number
  pPages: number
  /** 后端精确总条数（2026-10-17 审计 P2-43：此前用 pages × perPage 估算） */
  pCount: number
  /** 受控页码：避免 total 变化时 UiDataTable 自动复位到第 1 页 */
  pPage: number
  showSearchEmpty: boolean
}>()

const emit = defineEmits<{
  page: [event: { page: number; rows: number }]
  'view-supplier': [supplierName: string, orderNo: string]
}>()

// ============================================================
// 本页筛选（客户端，作用于当前页已合并的订单行）
// ============================================================
type FilterKey = 'all' | 'overdue' | 'pending'
const FILTERS: Array<{ key: FilterKey; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'overdue', label: '有逾期' },
  { key: 'pending', label: '未开始' },
]
const filterKey = ref<FilterKey>('all')

const filterCounts = computed<Record<FilterKey, number>>(() => {
  const rows = props.filteredRows
  return {
    all: rows.length,
    overdue: rows.filter((r) => r.hasOverdue).length,
    pending: rows.filter((r) => r.progress === 0).length,
  }
})

const visibleRows = computed<ProgressOrderRow[]>(() => {
  const rows = props.filteredRows
  if (filterKey.value === 'overdue') return rows.filter((r) => r.hasOverdue)
  if (filterKey.value === 'pending') return rows.filter((r) => r.progress === 0)
  return rows
})

const showSkeleton = computed(() => props.pIsLoading && !props.progressOrderRows.length)

const emptyText = computed(() => {
  if (props.showSearchEmpty) return '当前页无匹配的来料登记（搜索仅作用于当前页，可翻页或清空搜索）'
  if (filterKey.value !== 'all' && props.filteredRows.length) {
    const label = FILTERS.find((f) => f.key === filterKey.value)?.label ?? ''
    return `本页没有「${label}」的订单，可翻页查看其他页`
  }
  return '暂无进行中的来料登记'
})
const emptyIcon = computed(() => (props.showSearchEmpty || filterKey.value !== 'all' ? 'search' : 'inbox'))

// ============================================================
// 事件透传（订单卡 → 父级）
// ============================================================
function onViewSupplier(supplierName: string, orderNo: string) {
  emit('view-supplier', supplierName, orderNo)
}

// ============================================================
// 分页（UiPagination 用 1 基页码，父级沿用 PrimeVue 的 0 基契约）
// ============================================================
function onPage(page: number) {
  emit('page', { page: page - 1, rows: props.pPerPage })
}
function onPageSize(rows: number) {
  emit('page', { page: 0, rows })
}
</script>

<style scoped lang="scss">
.mr-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: white;
}

.mr-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* === 筛选条 === */
.mr-filterbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px 2px;
  flex-wrap: wrap;
}
.mr-filters {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  background: var(--color-surface, #f4f6fc);
  border-radius: 9px;
}
.mr-filter {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary, #475569);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.mr-filter:hover { background: rgba(255, 255, 255, 0.7); }
.mr-filter:focus-visible { outline: 2px solid var(--color-primary-600, #3a6bd6); outline-offset: 1px; }
.mr-filter.is-active {
  background: white;
  color: var(--color-primary-700, #2d5ab8);
  box-shadow: 0 1px 2px rgba(16, 32, 64, 0.08);
}
.mr-filter-n {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-muted, #64748b);
  font-variant-numeric: tabular-nums;
}
.mr-filter.is-active .mr-filter-n { color: var(--color-primary-700, #2d5ab8); }
.mr-filter-hint {
  margin-left: auto;
  font-size: 11px;
  color: var(--color-text-muted, #64748b);
  white-space: nowrap;
}

/* === 订单列表容器（单卡样式见 OrderCard.vue） === */
.mr-orders {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px 16px 16px;
}

/* === 空态 === */
.mr-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 56px 24px;
  color: var(--color-text-muted, #64748b);
  font-size: 13px;
  text-align: center;
}
.mr-empty svg { font-size: 26px; opacity: 0.45; }

/* === 骨架屏 === */
.mr-skel {
  border: 1px solid var(--color-border-light, #eef2f8);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mr-skel-head,
.mr-skel-row { display: flex; gap: 12px; }
.mr-skel-head span,
.mr-skel-row span {
  height: 10px;
  border-radius: 6px;
  background: #eef2f8;
  animation: mr-skel-pulse 1.4s ease-in-out infinite;
}
.mr-skel-head span:nth-child(1) { width: 140px; }
.mr-skel-head span:nth-child(2) { width: 220px; }
.mr-skel-head span:nth-child(3) { width: 90px; margin-left: auto; }
.mr-skel-row span:nth-child(1) { width: 22%; }
.mr-skel-row span:nth-child(2) { width: 34%; }
.mr-skel-row span:nth-child(3) { flex: 1; }
@keyframes mr-skel-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* === 取数进度条 === */
.mr-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  flex-shrink: 0;
}
.mr-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: mr-progress-slide 1s ease-in-out infinite;
}
@keyframes mr-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* === 响应式（订单头自身见 OrderCard.vue） === */
@media (max-width: 520px) {
  .mr-orders { padding: 8px 10px 12px; gap: 8px; }
  .mr-filterbar { padding: 8px 10px 2px; }
  .mr-filter { padding: 5px 9px; }
}
</style>

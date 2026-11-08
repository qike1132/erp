<template>
  <div class="mr-content">
    <div v-if="pIsFetching && progressOrderRows.length" class="mr-fetching-bar"><div class="mr-fetching-progress" /></div>

    <div class="mr-scroll">
      <!-- 工具条：按「数量事实」筛选 + 分组维度切换（作用域都是本页） -->
      <div v-if="progressOrderRows.length" class="mr-bar">
        <div class="mr-chips" role="group" aria-label="按到货情况筛选本页物料">
          <button
            v-for="f in FILTERS"
            :key="f.key"
            type="button"
            :class="['mr-chip', { 'is-active': filterKey === f.key }]"
            :aria-pressed="filterKey === f.key"
            @click="filterKey = f.key"
          >
            {{ f.label }}<span class="mr-chip-n">{{ counts[f.key] }}</span>
          </button>
        </div>

        <div class="mr-bar-right">
          <span class="mr-bar-hint">本页 {{ counts.total }} 项</span>
          <span class="mr-seg-label">分组</span>
          <div class="mr-seg" role="group" aria-label="切换分组维度">
            <button
              v-for="m in MODES"
              :key="m.key"
              type="button"
              :class="['mr-seg-btn', { 'is-active': groupMode === m.key }]"
              :aria-pressed="groupMode === m.key"
              @click="groupMode = m.key"
            >
              {{ m.label }}
            </button>
          </div>
        </div>
      </div>

      <!-- 首次加载骨架：保持表头位置，避免内容跳动 -->
      <div v-if="showSkeleton" class="mr-skel" aria-hidden="true">
        <div class="mr-skel-head"><span /><span /><span /><span /></div>
        <div v-for="i in 6" :key="i" class="mr-skel-row"><span /><span /><span /><span /></div>
      </div>

      <div v-else-if="!visibleRows.length" class="mr-empty">
        <FontAwesomeIcon :icon="emptyIcon" />
        <span>{{ emptyText }}</span>
      </div>

      <ProgressTable
        v-else
        :groups="groups"
        :mode="groupMode"
        :row-count="visibleRows.length"
        @view-detail="onViewDetail"
      />
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
 * ProgressTab.vue — 来料进度（扁平行列表 · 供应商/订单为分组维度）
 *
 * 2026-11-08 二次改版。上一版做成「订单卡 → 供应商块 → 物料行」三层卡片，
 * 被 owner 判定「UI 逻辑完全不行」。根因是违背了这个页面的**唯一业务事实**：
 * 它只登记两件事——到货时间、到货数量。
 *
 * 于是本版：
 *  · 行 = 一条登记里的一行物料（到货日期 + 到货数量 + 待收），表格扁平铺开，可纵向对比；
 *  · 供应商 / 订单降级为**视图模式**（分组行），不再是嵌套层级，也不再有卡片；
 *  · 「逾期」全部去掉：系统没有约定交期，只有 registration_date。改为如实显示
 *    「到货 MM-DD + 已等 N 天」，N≥30 且未收齐的标「≥30 天」（与后端 stats 同口径）；
 *  · 状态只表达数量事实：未到 / 部分到货 / 到齐；时间风险由日期列的色与字表达，
 *    两者不混在同一列（上一版把两种语义塞进「四档状态」是错的）；
 *  · 组头不报跨单位百分比：组内单位不一致时只报「x/y 项到齐」。
 *  · 窄屏（≤900px）每行重排为三行网格，不靠横向滚动。
 */
import { computed, ref } from 'vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import type { ProgressOrderRow } from '../composables/useMaterialRegistrations'
import type { GroupMode } from '../composables/progressRows'
import {
  flattenProgressRows,
  groupProgressRows,
  rowStatus,
  summarizeProgressRows,
} from '../composables/progressRows'
import ProgressTable from './ProgressTable.vue'

const props = defineProps<{
  /** 搜索过滤后的订单行（父级持有搜索词） */
  filteredRows: ProgressOrderRow[]
  /** 未过滤的订单行（fetching 提示与空态判断用） */
  progressOrderRows: ProgressOrderRow[]
  pIsLoading: boolean
  pIsFetching: boolean
  pPerPage: number
  pPages: number
  /** 后端精确总条数 */
  pCount: number
  /** 受控页码 */
  pPage: number
  showSearchEmpty: boolean
}>()

const emit = defineEmits<{
  page: [event: { page: number; rows: number }]
  'view-supplier': [supplierName: string, orderNo: string]
}>()

// ============================================================
// 筛选：只按「到货情况」这一种语义分档，避免混语义
// ============================================================
type FilterKey = 'all' | 'todo' | 'partial' | 'done' | 'slow'
const FILTERS: Array<{ key: FilterKey; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'todo', label: '未到' },
  { key: 'partial', label: '部分到货' },
  { key: 'done', label: '已到齐' },
  { key: 'slow', label: '≥30 天' },
]
const filterKey = ref<FilterKey>('all')

const MODES: Array<{ key: GroupMode; label: string }> = [
  { key: 'supplier', label: '按供应商' },
  { key: 'order', label: '按订单' },
  { key: 'none', label: '不分组' },
]
const groupMode = ref<GroupMode>('supplier')

/** 摊平后的全部行（当前页 × 搜索词） */
const allRows = computed(() => flattenProgressRows(props.filteredRows, new Date()))

const counts = computed(() => {
  const s = summarizeProgressRows(allRows.value)
  return { ...s, all: s.total }
})

const visibleRows = computed(() => {
  const rows = allRows.value
  if (filterKey.value === 'all') return rows
  if (filterKey.value === 'slow') return rows.filter((r) => r.isSlow)
  return rows.filter((r) => rowStatus(r) === filterKey.value)
})

const groups = computed(() => groupProgressRows(visibleRows.value, groupMode.value))

const showSkeleton = computed(() => props.pIsLoading && !props.progressOrderRows.length)

const emptyText = computed(() => {
  if (props.showSearchEmpty) return '当前页无匹配的来料登记（搜索仅作用于当前页，可翻页或清空搜索）'
  if (filterKey.value !== 'all' && allRows.value.length) {
    const label = FILTERS.find((f) => f.key === filterKey.value)?.label ?? ''
    return `本页没有「${label}」的物料，可翻页查看其他页`
  }
  return '暂无进行中的来料登记'
})
const emptyIcon = computed(() => (props.showSearchEmpty || filterKey.value !== 'all' ? 'search' : 'inbox'))

function onViewDetail(supplierName: string, orderNo: string) {
  emit('view-supplier', supplierName, orderNo)
}

// ============================================================
// 分页（UiPagination 用 1 基页码，父级沿用 0 基契约）
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

/* === 工具条：左筛选 · 右分组 === */
.mr-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px 8px;
  flex-wrap: wrap;
}
.mr-chips {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  background: var(--color-surface, #f4f6fc);
  border-radius: 9px;
}
.mr-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
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
.mr-chip:hover { background: rgba(255, 255, 255, 0.7); }
.mr-chip:focus-visible { outline: 2px solid var(--color-primary-600, #3a6bd6); outline-offset: 1px; }
.mr-chip.is-active {
  background: white;
  color: var(--color-primary-700, #2d5ab8);
  box-shadow: 0 1px 2px rgba(16, 32, 64, 0.08);
}
.mr-chip-n {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-muted, #64748b);
  font-variant-numeric: tabular-nums;
}
.mr-chip.is-active .mr-chip-n { color: var(--color-primary-700, #2d5ab8); }

.mr-bar-right {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.mr-bar-hint {
  font-size: 11px;
  color: var(--color-text-muted, #64748b);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.mr-seg-label { font-size: 11px; color: var(--color-text-muted, #64748b); }
.mr-seg {
  display: inline-flex;
  border: 1px solid var(--color-border-light, #e2e8f4);
  border-radius: 8px;
  overflow: hidden;
  background: white;
}
.mr-seg-btn {
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--color-text-secondary, #475569);
  background: transparent;
  border: none;
  padding: 4px 10px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.mr-seg-btn + .mr-seg-btn { border-left: 1px solid var(--color-border-light, #e2e8f4); }
.mr-seg-btn:hover { background: #f5f8ff; }
.mr-seg-btn:focus-visible { outline: 2px solid var(--color-primary-600, #3a6bd6); outline-offset: -2px; }
.mr-seg-btn.is-active {
  background: var(--color-primary-50, #eff5ff);
  color: var(--color-primary-700, #2d5ab8);
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

/* === 骨架 === */
.mr-skel { padding: 0 16px; }
.mr-skel-head,
.mr-skel-row {
  display: flex;
  gap: 14px;
  padding: 9px 10px;
  border-bottom: 1px solid #eef2f8;
}
.mr-skel-head span,
.mr-skel-row span {
  height: 9px;
  border-radius: 5px;
  background: #eef2f8;
  animation: mr-skel-pulse 1.4s ease-in-out infinite;
}
.mr-skel-head span:nth-child(1) { width: 60px; }
.mr-skel-head span:nth-child(2) { width: 150px; }
.mr-skel-head span:nth-child(3) { width: 180px; }
.mr-skel-head span:nth-child(4) { width: 90px; margin-left: auto; }
.mr-skel-row span:nth-child(1) { width: 60px; }
.mr-skel-row span:nth-child(2) { width: 150px; }
.mr-skel-row span:nth-child(3) { width: 180px; }
.mr-skel-row span:nth-child(4) { width: 90px; margin-left: auto; }
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

@media (max-width: 900px) {
  .mr-bar { padding: 8px 10px 6px; gap: 8px; }
  .mr-bar-right { width: 100%; margin-left: 0; justify-content: space-between; }
  .mr-seg-label { display: none; }
  .mr-skel { padding: 0 10px; }
}

@media (max-width: 520px) {
  .mr-chip { padding: 4px 8px; font-size: 11.5px; }
}
</style>

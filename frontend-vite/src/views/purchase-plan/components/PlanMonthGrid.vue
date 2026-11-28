<template>
  <div class="sp-grid-head">
    <span v-for="w in WDS_MON_FIRST" :key="w" :class="{ we: w === '六' || w === '日' }">{{ w }}</span>
  </div>

  <div class="sp-grid">
    <div
      v-for="c in cells"
      :key="c.key"
      class="sp-cell"
      :class="cellCls(c)"
      :role="c.row ? 'button' : undefined"
      :tabindex="c.row ? 0 : -1"
      :aria-label="c.row ? aria(c) : undefined"
      @click="pick(c)"
      @keydown.enter.prevent="pick(c)"
      @keydown.space.prevent="pick(c)"
    >
      <div class="sp-cell-top">
        <span class="sp-day">{{ c.day }}</span>
        <span v-if="c.weekday" class="sp-wd">{{ c.weekday }}</span>
        <span v-if="c.mark" class="sp-mark" :class="c.mark.cls">{{ c.mark.lbl }}</span>
      </div>

      <template v-if="c.row">
        <span class="sp-qty num">{{ fmt(c.row.totalQty) }}<small>件</small></span>
        <!-- 方案B（2026-11-28 拍板）：格子补上「谁在出货」——客户数·SKU数 + 客户占比条 -->
        <template v-if="c.meta">
          <span class="sp-cell-meta num">{{ c.meta.custs.length }} 客户 · {{ c.meta.skuN }} SKU</span>
          <div v-if="c.meta.custs.length" class="sp-share-bar" aria-hidden="true">
            <i
              v-for="seg in c.meta.custs"
              :key="seg.name"
              :style="{ flexGrow: seg.qty, background: custColor(seg.name) }"
            />
          </div>
        </template>
      </template>
      <span v-else-if="c.isToday" class="sp-today-hint">今天 · 无排产</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// 排产日历月视图 —— 每格：日总量 + 客户数·SKU数 + 客户占比条；
// 当日完整明细在右侧栏，格子不承担「既要概览又要明细」的双重职责。
import { computed } from 'vue'
import { buildMonthCells, dayMarkFor, startOfToday, todayIso } from './dayStatus'
import type { Row, DayCellMeta } from './types'
import { formatNumber as fmt } from '@/utils/format' // L-15（2026-11-21 审计）：删除 8 处各自为政的本地 fmt，统一千分位口径

const props = defineProps<{
  y: number
  m: number
  rows: Row[]
  /** 当前选中日期，用于高亮 */
  sel: string
  /** 搜索是否正在生效（生效时未命中的日子淡化） */
  searching: boolean
  matchedDates: Set<string>
  /** 当日客户数量分布与去重 SKU 数（父级从 skuDateIndex 派生） */
  dayMeta?: Record<string, DayCellMeta>
  /** 客户 → 展示色（父级按月度计划量排序分配，月历/明细/chips 三处同源） */
  custColors?: Record<string, string>
}>()

const emit = defineEmits<{
  select: [date: string]
}>()

/** 周一开头；与表头同源，避免两处各写一份星期序 */
const WDS_MON_FIRST = ['一', '二', '三', '四', '五', '六', '日']

const TODAY_MS = startOfToday()
const TODAY = todayIso()

/** 日期串 → 周几汉字。空格子也要显示周几，故统一由日期推导而非取 row._weekday。
    getDay() 以周日为 0，故 +6 后再取模换算成「周一为 0」的下标。 */
function weekdayOf(date: string): string {
  return WDS_MON_FIRST[(new Date(date + 'T00:00:00').getDay() + 6) % 7] ?? ''
}


const cells = computed(() =>
  buildMonthCells(props.y, props.m, props.rows).map(c => ({
    ...c,
    weekday: c.date ? weekdayOf(c.date) : '',
    isToday: c.date === TODAY,
    mark: c.row ? dayMarkFor(c.row, TODAY_MS) : null,
    meta: c.date ? (props.dayMeta?.[c.date] ?? null) : null,
    dim: props.searching && c.date !== null && !props.matchedDates.has(c.date),
  })),
)

function cellCls(c: (typeof cells.value)[number]): string[] {
  const cls: string[] = []
  if (!c.row) cls.push('sp-cell-empty')
  if (c.dim) cls.push('sp-cell-dim')
  if (c.isToday) cls.push('sp-cell-today')
  if (c.mark?.cls === 'st-r') cls.push('sp-cell-danger')
  else if (c.mark?.cls === 'st-a') cls.push('sp-cell-warn')
  else if (c.mark?.cls === 'st-g') cls.push('sp-cell-done')
  if (c.date && props.sel === c.date) cls.push('sp-cell-sel')
  return cls
}

/** 整格是一个可点击/可回车触发的操作，需要一句话说明其用途 */
function aria(c: (typeof cells.value)[number]): string {
  const r = c.row
  if (!r) return ''
  const meta = c.meta
  const who = meta ? `，${meta.custs.length} 家客户 ${meta.skuN} 个 SKU` : ''
  return `${c.day}日 周${c.weekday}，共 ${r.totalQty} 件${who}，查看当日明细`
}

function pick(c: (typeof cells.value)[number]): void {
  if (!c.date || !c.row) return
  emit('select', c.date)
}

function custColor(name: string): string {
  return props.custColors?.[name] ?? 'var(--color-slate-400, #94a3b8)'
}
</script>

<style scoped lang="scss">
.sp-grid-head {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
  padding: 12px 18px 8px;
}

.sp-grid-head span {
  font-size: var(--fs-caption);
  font-weight: 600;
  color: var(--color-text-muted);
  text-align: center;
}

.sp-grid-head span.we {
  color: var(--color-slate-400, #94a3b8);
}

.sp-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
  padding: 0 18px 16px;
}

.sp-cell {
  position: relative;
  min-height: 92px;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: var(--radius-sm, 10px);
  background: white;
  padding: 8px 9px 9px 11px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  box-sizing: border-box;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}

/* 状态用左侧色条表达而非整格染色：整格染色会把正文压在同色背景上降低可读性，
   且多张同状态格子并排时满屏色块、彼此无法区分。 */
.sp-cell::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: transparent;
}

.sp-cell[role='button'] {
  cursor: pointer;
}

.sp-cell[role='button']:hover {
  border-color: var(--color-primary-300);
  box-shadow: 0 2px 8px rgba(176, 224, 230, 0.35);
}

.sp-cell:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

.sp-cell-danger::before { background: var(--color-danger-500); }
.sp-cell-warn::before { background: var(--color-warning-500); }
.sp-cell-done::before { background: var(--color-success-500); }

.sp-cell-danger { background: var(--color-danger-50); border-color: var(--color-danger-200); }
.sp-cell-warn { background: var(--color-warning-50); border-color: var(--color-warning-200); }
.sp-cell-done { background: var(--color-success-50); border-color: var(--color-success-200); }

.sp-cell-sel {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

/* 未命中搜索：整体淡化但仍可读 */
.sp-cell-dim { opacity: 0.4; }

.sp-cell-empty {
  background: var(--color-slate-50, #f8fafc);
  border-color: var(--color-slate-100, #f1f5f9);
}

.sp-cell-empty .sp-day,
.sp-cell-empty .sp-wd {
  color: var(--color-slate-300, #cbd5e1);
}

.sp-cell-top {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.sp-day {
  font-size: var(--fs-body-sm);
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1;
}

.sp-wd {
  font-size: var(--fs-caption);
  font-weight: 600;
  color: var(--color-text-muted);
}

/* 今天：日号做成主色胶囊，一眼定位 */
.sp-cell-today .sp-day,
.sp-cell-today .sp-wd {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  border-radius: 7px;
  padding: 2px 6px;
}

.sp-mark {
  margin-left: auto;
  font-size: var(--fs-caption);
  font-weight: 700;
  line-height: 1;
  padding: 3px 6px;
  border-radius: 6px;
  white-space: nowrap;
}

.st-r { background: var(--color-danger-100); color: var(--color-danger-700); }
.st-a { background: var(--color-warning-100); color: var(--color-warning-700); }
.st-g { background: var(--color-success-100); color: var(--color-success-700); }

.sp-qty {
  font-size: var(--fs-body);
  font-weight: 800;
  line-height: 1;
  color: var(--color-heading);
  letter-spacing: -0.02em;
}

.sp-qty small {
  font-size: var(--fs-caption);
  font-weight: 600;
  color: var(--color-text-muted);
  margin-left: 1px;
}

.sp-cell-meta {
  font-size: var(--fs-caption);
  font-weight: 600;
  color: var(--color-text-muted, #8c96ad);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 客户占比条：flex-grow 按数量分配宽度，天然防溢出 */
.sp-share-bar {
  margin-top: auto;
  height: 4px;
  display: flex;
  gap: 1px;
  overflow: hidden;
}

.sp-share-bar i {
  flex: 1 1 0;
  min-width: 2px;
  display: block;
}

.sp-today-hint {
  margin-top: auto;
  font-size: var(--fs-caption);
  font-weight: 700;
  color: var(--color-primary-600);
}
</style>

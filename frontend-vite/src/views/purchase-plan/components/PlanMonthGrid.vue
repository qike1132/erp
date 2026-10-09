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
        <span class="sp-cell-meta">
          <span>{{ c.row.customerCount }}客户</span>
          <i aria-hidden="true" />
          <span>{{ c.row.planCount }}产品</span>
        </span>
        <span class="sp-bar">
          <i :class="barCls(c.row._producedPct)" :style="{ width: c.row._producedPct + '%' }" />
        </span>
        <!-- 「全部」视图下叠加工厂构成条：一眼看出当天计划里各厂占比 -->
        <span v-if="factory === 'all'" class="sp-fbar" aria-hidden="true">
          <i v-for="seg in fbar(c.row)" :key="seg.f" :class="`fb-${factoryTone(seg.f)}`" :style="{ width: seg.w + '%' }" />
        </span>
      </template>
      <span v-else-if="c.isToday" class="sp-today-hint">今天 · 无排产</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// 排产日历月视图 —— 取代原来的「有排产的日期」卡片列表。
// 整月一次铺开（空格子代表当天无排产，本身也是信息），每格只放聚合值；
// 当日完整明细在右侧栏，格子不再承担「既要概览又要明细」的双重职责。
import { computed } from 'vue'
import { buildMonthCells, dayMarkFor, startOfToday, todayIso } from './dayStatus'
import { factoryTone } from './factoryMeta'
import type { Row } from './types'

const props = defineProps<{
  y: number
  m: number
  rows: Row[]
  /** 当前选中日期，用于高亮 */
  sel: string
  /** 搜索是否正在生效（生效时未命中的日子淡化） */
  searching: boolean
  matchedDates: Set<string>
  /** 当前工厂筛选；'all' 时格内叠加工厂构成条 */
  factory: string
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

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN')
}

/** 进度条配色与卡片/表格同口径：0 未出、未满 100 部分、100 完成 */
function barCls(pct: number): string {
  if (pct <= 0) return 'sp-bar-r'
  if (pct < 100) return 'sp-bar-a'
  return 'sp-bar-g'
}

/** 「全部」视图下格内的工厂构成条：按各厂当日计划量占比铺色 */
function fbar(row: Row): { f: string; w: number }[] {
  const fac = row.factories
  if (!fac) return []
  const entries = Object.entries(fac).filter(([, a]) => a.qty > 0)
  const total = entries.reduce((n, [, a]) => n + a.qty, 0)
  if (total <= 0) return []
  return entries.map(([f, a]) => ({ f, w: (a.qty / total) * 100 }))
}

const cells = computed(() =>
  buildMonthCells(props.y, props.m, props.rows).map(c => ({
    ...c,
    weekday: c.date ? weekdayOf(c.date) : '',
    isToday: c.date === TODAY,
    mark: c.row ? dayMarkFor(c.row, TODAY_MS) : null,
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
  return `${c.day}日 周${c.weekday}，共 ${r.totalQty} 件，${r.customerCount} 家客户 ${r.planCount} 个产品，查看当日明细`
}

function pick(c: (typeof cells.value)[number]): void {
  if (!c.date || !c.row) return
  emit('select', c.date)
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
  font-size: 11px;
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
  min-height: 96px;
  border: 1px solid var(--color-border-light, #f0f2f5);
  border-radius: var(--radius-sm, 10px);
  background: white;
  padding: 8px 9px 8px 11px;
  display: flex;
  flex-direction: column;
  gap: 5px;
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
  font-size: 13px;
  font-weight: 800;
  color: var(--color-heading);
  line-height: 1;
}

.sp-wd {
  font-size: 10px;
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
  font-size: 10px;
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
  margin-top: auto;
  font-size: 16px;
  font-weight: 800;
  line-height: 1;
  color: var(--color-heading);
  letter-spacing: -0.02em;
}

.sp-qty small {
  font-size: 9px;
  font-weight: 600;
  color: var(--color-text-muted);
  margin-left: 1px;
}

.sp-cell-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
}

.sp-cell-meta i {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.5;
  flex-shrink: 0;
}

.sp-today-hint {
  margin-top: auto;
  font-size: 10px;
  font-weight: 700;
  color: var(--color-primary-600);
}

.sp-bar {
  display: block;
  height: 4px;
  border-radius: 2px;
  background: rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.sp-bar > i {
  display: block;
  height: 100%;
  border-radius: 2px;
}

.sp-bar-r { background: var(--color-danger-500); }
.sp-bar-a { background: var(--color-warning-500); }
.sp-bar-g { background: var(--color-success-500); }

/* 工厂构成条（仅「全部」视图）：与进度条同宽同高，颜色区分工厂 */
.sp-fbar {
  display: flex;
  height: 4px;
  border-radius: 2px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.04);
}

.sp-fbar > i {
  display: block;
  height: 100%;
}

.fb-dg { background: var(--color-primary-500, #5b8def); }
.fb-hb { background: var(--color-purple-500, #8b5cf6); }
.fb-other { background: var(--color-slate-300, #cbd5e1); }
</style>

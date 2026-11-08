<template>
  <section :class="['mr-group', `st-${statusKey}`]">
    <!-- 供应商层：整行可点，左轨色 + 状态词 + 进度条，与物料行共用列轨道 -->
    <div
      class="mr-grp-head"
      role="button"
      tabindex="0"
      :aria-expanded="!collapsed"
      :aria-label="ariaLabel"
      @click="emit('toggle')"
      @keydown.enter.prevent="emit('toggle')"
      @keydown.space.prevent="emit('toggle')"
    >
      <span class="mr-grp-name">
        <span class="mr-grp-title" :title="group.supplierName">{{ group.supplierName }}</span>
        <span :class="['mr-chip', `is-${statusKey}`]">{{ statusText }}</span>
      </span>

      <span class="mr-grp-count">{{ doneCount }}/{{ group.items.length }} 项已到</span>

      <span class="mr-grp-bar" :title="`已到 ${doneCount} / ${group.items.length} 项，数量进度 ${group.progress}%`">
        <i :style="{ width: clampPct(group.progress) }" />
      </span>

      <span class="mr-grp-pct">{{ group.progress }}%</span>

      <FontAwesomeIcon
        :class="['mr-grp-chev', { 'is-collapsed': collapsed }]"
        icon="chevron-down"
        aria-hidden="true"
      />
    </div>

    <!-- 物料层：名称 · 已到/采购 · 进度条 · 百分比；逾期在名称后带文字徽标 -->
    <ul v-if="!collapsed" class="mr-mats">
      <li v-for="i in group.items" :key="i.id + '|' + i.material_name" :class="['mr-mat', { 'is-overdue': i.overdue }]">
        <span class="mr-mat-name" :title="`${i.material_name}${i.specification ? ' ' + i.specification : ''}`">
          <span class="mr-mat-text">{{ i.material_name }}</span>
          <em v-if="i.specification">{{ i.specification }}</em>
          <span v-if="i.overdue" class="mr-flag">逾期</span>
        </span>

        <span class="mr-mat-qty" :title="`已到 ${i.received_display} / 采购 ${i.ordered_display} ${i.unit || ''}`">
          <b>{{ i.received_display }}</b> / {{ i.ordered_display }} {{ i.unit || '' }}
        </span>

        <span class="mr-mat-bar">
          <i :class="meterClass(i)" :style="{ width: clampPct(i.progress) }" />
        </span>

        <span :class="['mr-mat-pct', { 'is-danger': i.overdue }]">{{ i.progress }}%</span>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
/**
 * SupplierGroupCard.vue — 供应商分组（订单卡内的一个供应商块）
 *
 * 2026-11-08 改版：
 *  · 供应商行与物料行共用列轨道（名称 / 已到·采购 / 进度条 / 百分比 / 折叠位），
 *    跨层级纵向对齐，层级只靠 3px 左轨 + 缩进表达，不再套一层带边框的小卡片。
 *  · 组头不再重复一根 64px 迷你条——与下方物料条同源，重复即噪音。
 *  · 数量聚合只做「项数」（x/y 项已到）：组内物料单位可能不同，跨单位求和无意义。
 *  · 四档状态同时给色与词（逾期/已到齐/进行中/未开始），不依赖颜色单独传达。
 */
import { computed } from 'vue'
import type { SupplierGroupRow, MergedItem } from '../composables/useMaterialRegistrations'

const props = defineProps<{
  group: SupplierGroupRow
  collapsed: boolean
}>()

const emit = defineEmits<{ toggle: [] }>()

type StatusKey = 'overdue' | 'done' | 'ongoing' | 'pending'

/** 组状态：逾期 > 已到齐 > 进行中 > 未开始（与订单分段条/物料条同口径） */
const statusKey = computed<StatusKey>(() => {
  if (props.group.overdue) return 'overdue'
  if (props.group.progress >= 100) return 'done'
  if (props.group.progress > 0) return 'ongoing'
  return 'pending'
})

const STATUS_TEXT: Record<StatusKey, string> = {
  overdue: '逾期',
  done: '已到齐',
  ongoing: '进行中',
  pending: '未开始',
}
const statusText = computed(() => STATUS_TEXT[statusKey.value])

/** 已到齐的物料项数（数量全部到货） */
const doneCount = computed(
  () => props.group.items.filter((i) => i.received_quantity >= i.ordered_quantity).length,
)

const ariaLabel = computed(() => {
  const g = props.group
  const parts = [
    g.supplierName,
    statusText.value,
    `${doneCount.value} / ${g.items.length} 项已到`,
    `数量进度 ${g.progress}%`,
    props.collapsed ? '已收起' : '已展开',
  ]
  return parts.join('，')
})

/** 物料条色档：逾期 > 已到齐 > 进行中 > 未动 */
function meterClass(i: MergedItem): string {
  if (i.overdue) return 'fill-overdue'
  if (i.progress >= 100 || i.received_quantity >= i.ordered_quantity) return 'fill-done'
  if (i.progress > 0 || i.received_quantity > 0) return 'fill-ongoing'
  return 'fill-zero'
}

function clampPct(n: number): string {
  return `${Math.min(Math.max(n, 0), 100)}%`
}
</script>

<style scoped lang="scss">
/* === 状态四色（dataviz 校验档；仅本模块作用域，不动全局主题） === */
.mr-group {
  --st: #3a6bd6;
  --track: #e9eef6;
  border-left: 3px solid var(--st);
  background: white;
}
.mr-group.st-overdue { --st: #d03b3b; }
.mr-group.st-done { --st: #1e9e55; }
.mr-group.st-ongoing { --st: #3a6bd6; }
.mr-group.st-pending { --st: #9a6a00; }

.mr-group + .mr-group { border-top: 1px solid var(--color-border-light, #eef2f8); }

/* === 供应商行（与物料行共用列轨道） === */
.mr-grp-head,
.mr-mat {
  display: grid;
  /* 名称列吃剩余空间，进度条列封顶——否则条会拉成横贯全行的大色块，压掉名称可读性 */
  grid-template-columns: minmax(0, 1.5fr) minmax(96px, auto) minmax(110px, 180px) 46px 20px;
  align-items: center;
  column-gap: 12px;
}

.mr-grp-head {
  padding: 8px 14px 8px 11px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.mr-grp-head:hover { background: #f8faff; }
.mr-grp-head:focus-visible { outline: 2px solid var(--st); outline-offset: -2px; }

.mr-grp-name { display: flex; align-items: center; gap: 7px; min-width: 0; }
.mr-grp-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text, #1a1a2e);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mr-chip {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.5;
  padding: 1px 7px;
  border-radius: 999px;
}
.mr-chip.is-overdue { color: #b3261e; background: #fdeaea; }
.mr-chip.is-done { color: #157a42; background: #e6f7ee; }
.mr-chip.is-ongoing { color: #2d5ab8; background: #e8f0fd; }
.mr-chip.is-pending { color: #8a5f00; background: #fdf3e0; }

.mr-grp-count {
  font-size: 11.5px;
  color: var(--color-text-muted, #64748b);
  text-align: right;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.mr-grp-bar,
.mr-mat-bar {
  display: block;
  height: 8px;
  border-radius: 999px;
  background: var(--track);
  overflow: hidden;
}
.mr-grp-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--st);
  transition: width 0.3s ease;
}

.mr-grp-pct,
.mr-mat-pct {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text, #1a1a2e);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.mr-grp-chev {
  font-size: 10px;
  color: var(--color-text-placeholder, #94a3b8);
  justify-self: center;
  transition: transform 0.18s ease;
}
.mr-grp-chev.is-collapsed { transform: rotate(-90deg); }

/* === 物料行 === */
.mr-mats {
  list-style: none;
  margin: 0;
  padding: 0 14px 8px 11px;
  display: flex;
  flex-direction: column;
}

.mr-mat {
  padding: 4px 0;
  border-radius: 6px;
  transition: background 0.15s;
}
.mr-mat:hover { background: #f8faff; }

.mr-mat-name {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  padding-left: 14px; /* 首列缩进表达从属关系；其余列与供应商行保持对齐 */
  font-size: 12.5px;
  font-weight: 500;
  color: var(--color-text-secondary, #475569);
}
.mr-mat-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mr-mat-name em {
  flex-shrink: 0;
  font-style: normal;
  font-size: 11px;
  color: var(--color-text-placeholder, #94a3b8);
}

.mr-flag {
  flex-shrink: 0;
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1.5;
  color: #b3261e;
  background: #fdeaea;
  padding: 0 6px;
  border-radius: 999px;
}

.mr-mat-qty {
  font-size: 12px;
  color: var(--color-text-muted, #64748b);
  text-align: right;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.mr-mat-qty b { font-weight: 700; color: var(--color-text-secondary, #475569); }

.mr-mat-bar { height: 6px; }
.mr-mat-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  transition: width 0.3s ease;
}
.mr-mat-bar i.fill-overdue { background: #d03b3b; }
.mr-mat-bar i.fill-done { background: #1e9e55; }
.mr-mat-bar i.fill-ongoing { background: #3a6bd6; }
.mr-mat-bar i.fill-zero { background: #c9a25e; }

.mr-mat-pct { font-size: 11.5px; }
.mr-mat-pct.is-danger { color: #b3261e; }

/* === 响应式：≤860px 供应商/物料行降为两行网格，不再依赖横向滚动 === */
@media (max-width: 860px) {
  .mr-grp-head {
    grid-template-columns: minmax(0, 1fr) auto auto 18px;
    grid-template-areas:
      'name count pct chev'
      'bar bar bar bar';
    row-gap: 6px;
    padding: 8px 10px 8px 9px;
  }
  .mr-grp-name { grid-area: name; }
  .mr-grp-count { grid-area: count; }
  .mr-grp-pct { grid-area: pct; }
  .mr-grp-chev { grid-area: chev; }
  .mr-grp-bar { grid-area: bar; }

  .mr-mat {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      'name pct'
      'bar qty';
    row-gap: 5px;
    column-gap: 10px;
    padding: 6px 0;
  }
  .mr-mat-name { grid-area: name; padding-left: 8px; }
  .mr-mat-pct { grid-area: pct; }
  .mr-mat-bar { grid-area: bar; }
  .mr-mat-qty { grid-area: qty; font-size: 11px; }

  .mr-mats { padding: 0 10px 8px 9px; }
}

/* 手机：项数让位给名称，进度条独占一行 */
@media (max-width: 520px) {
  .mr-grp-head {
    grid-template-columns: minmax(0, 1fr) auto 18px;
    grid-template-areas:
      'name pct chev'
      'bar bar bar';
  }
  .mr-grp-count { display: none; }
}
</style>

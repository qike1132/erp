<template>
  <div class="mr-supplier-group" :class="{ 'is-overdue': group.overdue }">
    <div class="mr-supplier-label" role="button" tabindex="0" :aria-expanded="!collapsed" :aria-label="`${group.supplierName}，${group.items.length} 项物料，进度 ${group.progress}%${group.overdue ? '，逾期' : ''}`" @click="emit('toggle')" @keyup.enter="emit('toggle')">
      <FontAwesomeIcon icon="truck" />
      <span class="mr-supplier-name">{{ group.supplierName }}</span>
      <span v-if="group.overdue" class="mr-overdue-tag">逾期</span>
      <span class="mr-supplier-mini"><i :class="miniClass" :style="{ width: group.progress + '%' }" /></span>
      <span class="mr-supplier-pct">{{ group.progress }}%</span>
      <span class="mr-supplier-count">{{ group.items.length }} 项</span>
      <span class="mr-expand-icon" aria-hidden="true">{{ collapsed ? '▶' : '▼' }}</span>
    </div>
    <div v-if="!collapsed" class="mr-items-container">
      <div v-for="i in group.items" :key="i.material_name" class="mr-mat-row">
        <span class="mr-mat-name" :title="i.material_name">{{ i.material_name }}</span>
        <span class="mr-mat-qty" :title="`已到货 ${i.received_display} / 采购 ${i.ordered_display} ${i.unit || ''}`">
          <b>{{ i.received_display }}</b> / {{ i.ordered_display }} {{ i.unit || '' }}
        </span>
        <span :class="['mr-mat-meter', meterClass(i)]" :style="{ '--fill': meterWidth(i) }" />
        <span class="mr-mat-pct" :class="{ 'is-overdue-txt': i.overdue }">{{ i.progress }}%</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * SupplierGroupCard.vue — 供应商分组块（方案A改版）
 *
 * 一条来料登记 = 一个供应商块（后端 item 级无 supplier_name，登记级才有）。
 * 默认展开由父级控制：父级记"已收起"集合（collapse 语义反转，未记录即展开）。
 * 状态四色为 dataviz 校验档（对比度 ≥3:1、CVD ΔE 达标），以局部变量落在卡片内：
 *   未动=琥珀棕 / 进行中=蓝 / 已到齐=绿 / 逾期=红；每个状态同时带文字（mini 条旁的
 *   百分比与"逾期"徽标），不依赖颜色单独传达。
 */
import type { SupplierGroupRow, MergedItem } from '../composables/useMaterialRegistrations'

defineProps<{
  orderNo: string
  group: SupplierGroupRow
  collapsed: boolean
}>()

const emit = defineEmits<{ toggle: [] }>()

/** 组头部 mini 条色：跟组状态（逾期优先级最高） */
function miniClass(group: SupplierGroupRow): string {
  if (group.overdue) return 'fill-overdue'
  if (group.progress >= 100) return 'fill-done'
  if (group.progress > 0) return 'fill-ongoing'
  return 'fill-zero'
}

/** 物料 meter 色档：逾期 > 已到齐 > 进行中 > 未动 */
function meterClass(i: MergedItem): string {
  if (i.overdue) return 'fill-overdue'
  if (i.progress >= 100 || i.received_quantity >= i.ordered_quantity) return 'fill-done'
  if (i.progress > 0 || i.received_quantity > 0) return 'fill-ongoing'
  return 'fill-zero'
}

/** meter 宽度：填充量 = 到货进度（未动时轨道全空但着琥珀色以示"未开始"） */
function meterWidth(i: MergedItem): string {
  const pct = Math.min(Math.max(i.progress, 0), 100)
  return pct + '%'
}
</script>

<style scoped lang="scss">
/* === 状态四色（dataviz 六项校验档；仅本模块作用域，不动全局主题） === */
.mr-supplier-group {
  --st-ongoing: #3a6bd6;
  --st-done: #1e9e55;
  --st-zero: #9a6a00;
  --st-overdue: #d03b3b;
  --track: #dce8fb;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  background: var(--color-surface, #fafbfe);
  overflow: hidden;
}
.mr-supplier-group.is-overdue { border-color: rgba(208, 59, 59, 0.35); }

.mr-supplier-label {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: #f4f7fd;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text, #1a1a2e);
  cursor: pointer;
  user-select: none;
}
.mr-supplier-label:focus-visible { outline: 2px solid var(--st-ongoing); outline-offset: -2px; }
.mr-supplier-label svg { font-size: 11px; color: var(--st-ongoing); flex-shrink: 0; }
.mr-supplier-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px; }

.mr-overdue-tag {
  font-size: 10.5px;
  font-weight: 700;
  color: white;
  background: var(--st-overdue);
  padding: 1px 7px;
  border-radius: 999px;
  flex-shrink: 0;
}

.mr-supplier-mini {
  width: 64px;
  height: 5px;
  border-radius: 3px;
  background: var(--track);
  overflow: hidden;
  flex-shrink: 0;
  display: inline-block;
}
.mr-supplier-mini i { display: block; height: 100%; border-radius: 3px; }

.mr-supplier-pct { font-size: 11px; font-weight: 700; color: var(--color-text-secondary, #475569); font-variant-numeric: tabular-nums; flex-shrink: 0; }
.mr-supplier-count { margin-left: auto; font-size: 11px; font-weight: 500; color: var(--color-text-muted, #94a3b8); flex-shrink: 0; }
.mr-expand-icon { margin-left: 4px; font-size: 10px; color: var(--color-text-muted, #94a3b8); flex-shrink: 0; }

/* 色档：mini 条与物料 meter 共用 */
.mr-supplier-mini .fill-ongoing, .mr-mat-meter .fill-ongoing { background: var(--st-ongoing); }
.mr-supplier-mini .fill-done, .mr-mat-meter .fill-done { background: var(--st-done); }
.mr-supplier-mini .fill-zero, .mr-mat-meter .fill-zero { background: var(--st-zero); }
.mr-supplier-mini .fill-overdue, .mr-mat-meter .fill-overdue { background: var(--st-overdue); }

/* === 物料行（默认展开） === */
.mr-items-container { padding: 6px 12px 8px; display: flex; flex-direction: column; gap: 5px; background: white; }

.mr-mat-row {
  display: grid;
  grid-template-columns: minmax(130px, 1.2fr) minmax(120px, auto) minmax(80px, 1fr) 44px;
  align-items: center;
  gap: 10px;
  padding: 3px 4px;
  border-radius: 6px;
  font-size: 12px;
}
.mr-mat-row:hover { background: #f4f7fd; }

.mr-mat-name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mr-mat-qty { text-align: right; color: var(--color-text-secondary, #475569); white-space: nowrap; font-variant-numeric: tabular-nums; }
.mr-mat-qty b { color: var(--st-done); font-weight: 600; }

.mr-mat-meter {
  position: relative;
  height: 8px;
  border-radius: 0 4px 4px 0;
  background: var(--track);
  overflow: hidden;
  display: block;
}
.mr-mat-meter::after {
  content: '';
  position: absolute;
  inset: 0;
  width: var(--fill, 0%);
  border-radius: inherit;
  background: inherit;
  opacity: 0; /* 兜底：老浏览器无填充时也保持轨道可见 */
}
/* 填充实现：色档类先铺满整条（表示状态），再由 --fill 以表面色遮罩截断 */
.mr-mat-meter.fill-ongoing { background: linear-gradient(to right, var(--st-ongoing) var(--fill, 0%), var(--track) var(--fill, 0%)); }
.mr-mat-meter.fill-done { background: linear-gradient(to right, var(--st-done) var(--fill, 0%), var(--track) var(--fill, 0%)); }
.mr-mat-meter.fill-zero { background: linear-gradient(to right, var(--st-zero) var(--fill, 0%), var(--track) var(--fill, 0%)); }
.mr-mat-meter.fill-overdue { background: linear-gradient(to right, var(--st-overdue) var(--fill, 0%), var(--track) var(--fill, 0%)); }

.mr-mat-pct { text-align: right; font-size: 11px; font-weight: 700; color: var(--color-text-secondary, #475569); font-variant-numeric: tabular-nums; }
.mr-mat-pct.is-overdue-txt { color: var(--st-overdue); }
</style>

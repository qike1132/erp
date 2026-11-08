<template>
  <article
    :class="['mr-order', { 'is-overdue': row.hasOverdue }]"
    :aria-label="`订单 ${row.orderNo}，${row.groups.length} 家供应商，总进度 ${row.progress}%${row.hasOverdue ? '，存在逾期物料' : ''}`"
  >
    <!-- 订单一层：身份 · 摘要 · 总进度 · 唯一入口 -->
    <header class="mr-order-head">
      <div class="mr-order-id">
        <span class="mr-order-no">{{ row.orderNo }}</span>
        <span class="mr-order-date">{{ row.poCreateTime || '—' }}</span>
      </div>

      <div class="mr-order-meta">
        <span class="mr-cust">{{ row.customerName || '—' }}</span>
        <span class="mr-meta-sep" aria-hidden="true">·</span>
        <span class="mr-prod" :title="productNames">{{ productNames }}</span>
        <span class="mr-qty" :title="`订单数量 ${row.productQuantity ?? '—'}`">
          <em>数量</em>{{ row.productQuantity != null ? fmtQty(row.productQuantity) : '—' }}
        </span>
      </div>

      <div class="mr-order-sum">
        <span class="mr-sum">{{ row.groups.length }} 家供应商</span>
        <span class="mr-sum">待收 {{ pendingCount }} 项</span>
        <span v-if="row.hasOverdue" class="mr-sum is-danger">逾期 {{ overdueCount }} 项</span>
        <span class="mr-order-progress" :title="`总进度 ${row.progress}%`">
          <span class="mr-order-bar"><i :style="{ width: clampPct(row.progress) }" /></span>
          <b>{{ row.progress }}%</b>
        </span>
        <button
          type="button"
          class="mr-order-btn"
          :aria-label="`查看订单 ${row.orderNo} 的供应商明细`"
          @click="emit('view-supplier', row.groups[0]?.supplierName || '', row.orderNo)"
        >
          查看明细
        </button>
      </div>
    </header>

    <!-- 供应商一层 + 物料一层：共用列轨道，层级靠左轨与缩进表达 -->
    <SupplierGroupCard
      v-for="grp in row.groups"
      :key="groupKey(grp)"
      :group="grp"
      :collapsed="collapsedGroups.has(groupKey(grp))"
      @toggle="toggleGroup(groupKey(grp))"
    />
  </article>
</template>

<script setup lang="ts">
/**
 * OrderCard.vue — 单个采购订单卡（订单头 + 供应商分组清单）
 *
 * 从 ProgressTab 抽出：ProgressTab 已到 513 行，触到 quality_gate 的
 * 「前端巨型 Vue 组件」400 行阈值（2026-11-08 提交被拒）。抽取边界按职责：
 * 本组件只关心「一个订单」的展示与它自己的收起状态，分页/筛选/空态留在父级。
 *
 * 收起语义沿用「默认展开」：Set 记录的是用户手动收起的组，不是展开的组。
 */
import { computed, reactive } from 'vue'
import type { ProgressOrderRow, SupplierGroupRow } from '../composables/useMaterialRegistrations'
import { formatQuantity } from '@/utils/quantity'
import SupplierGroupCard from './SupplierGroupCard.vue'

const props = defineProps<{ row: ProgressOrderRow }>()

const emit = defineEmits<{
  'view-supplier': [supplierName: string, orderNo: string]
}>()

// ============================================================
// 收起状态：按「供应商 + 登记日期」记忆，默认全部展开
// ============================================================
const collapsedGroups = reactive(new Set<string>())

/** 同单同供应商可能有多条登记，必须带登记日期才唯一 */
function groupKey(grp: SupplierGroupRow): string {
  return `${props.row.orderNo}|${grp.supplierName}|${grp.registrationDate}`
}

function toggleGroup(key: string) {
  if (collapsedGroups.has(key)) collapsedGroups.delete(key)
  else collapsedGroups.add(key)
}

// ============================================================
// 展示口径
// ============================================================
/** 订单内未收齐的物料项数（待处理事项） */
const pendingCount = computed(() =>
  props.row.groups.reduce((s, g) => s + g.items.filter((i) => i.received_quantity < i.ordered_quantity).length, 0),
)

/** 订单内逾期物料项数（超 30 天且未收齐） */
const overdueCount = computed(() =>
  props.row.groups.reduce((s, g) => s + g.items.filter((i) => i.overdue).length, 0),
)

/** 多 SKU 订单：产品名并列展示（完整列表放 title） */
const productNames = computed(() => {
  const skus = props.row.skuItems
  if (skus && skus.length > 1) return skus.map((s) => s.product_name).filter(Boolean).join(' · ')
  return props.row.productName || '—'
})

function clampPct(n: number): string {
  return `${Math.min(Math.max(n, 0), 100)}%`
}

/** 订单数量千分位 */
function fmtQty(n: number): string {
  return formatQuantity(n)
}
</script>

<style scoped lang="scss">
.mr-order {
  border: 1px solid var(--color-border-light, #e8edf5);
  border-radius: 12px;
  background: white;
  overflow: hidden;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.mr-order:hover { border-color: var(--color-border-strong, #cbd5e1); box-shadow: 0 1px 6px rgba(16, 32, 64, 0.05); }
.mr-order.is-overdue { border-color: rgba(208, 59, 59, 0.32); }

.mr-order-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 9px 14px;
  background: #fbfcff;
  border-bottom: 1px solid var(--color-border-light, #eef2f8);
  flex-wrap: wrap;
}
.mr-order-id { display: flex; flex-direction: column; gap: 1px; flex-shrink: 0; }
.mr-order-no {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-primary-700, #2d5ab8);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
}
.mr-order-date {
  font-size: 11px;
  color: var(--color-text-muted, #64748b);
  font-variant-numeric: tabular-nums;
}

.mr-order-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  flex: 1 1 220px;
  font-size: 12px;
  color: var(--color-text-secondary, #475569);
}
.mr-cust { font-weight: 600; color: var(--color-text, #1a1a2e); white-space: nowrap; }
.mr-meta-sep { color: var(--color-text-placeholder, #94a3b8); }
.mr-prod {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mr-qty {
  flex-shrink: 0;
  color: var(--color-text, #1a1a2e);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.mr-qty em {
  font-style: normal;
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted, #64748b);
  margin-right: 4px;
}

.mr-order-sum {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
  margin-left: auto;
}
.mr-sum {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-secondary, #475569);
  background: #eef2f9;
  border-radius: 999px;
  padding: 2px 9px;
  white-space: nowrap;
}
.mr-sum.is-danger { color: #b3261e; background: #fdeaea; }

.mr-order-progress { display: inline-flex; align-items: center; gap: 7px; }
.mr-order-bar {
  display: block;
  width: 84px;
  height: 6px;
  border-radius: 999px;
  background: #e6ebf3;
  overflow: hidden;
}
.mr-order-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary-600, #3a6bd6);
}
.mr-order-progress b {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text, #1a1a2e);
  font-variant-numeric: tabular-nums;
  min-width: 32px;
  text-align: right;
}

.mr-order-btn {
  font-family: inherit;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-700, #2d5ab8);
  background: white;
  border: 1px solid var(--color-primary-200, #b8ccff);
  border-radius: 8px;
  padding: 5px 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s, border-color 0.15s;
}
.mr-order-btn:hover { background: var(--color-primary-50, #eff5ff); border-color: var(--color-primary-400, #6d95f0); }
.mr-order-btn:focus-visible { outline: 2px solid var(--color-primary-600, #3a6bd6); outline-offset: 1px; }

/* === 响应式（订单头自身；列表容器与筛选条见 ProgressTab） === */
@media (max-width: 1100px) {
  .mr-order-head { gap: 10px; }
  .mr-order-progress .mr-order-bar { width: 60px; }
}

@media (max-width: 520px) {
  /* 窄屏改为纵排：身份 → 客户/产品/数量 → 摘要与进度，不再横向挤压 */
  .mr-order-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
    padding: 8px 10px;
  }
  .mr-order-meta { flex-wrap: wrap; row-gap: 2px; }
  .mr-order-sum { margin-left: 0; flex-wrap: wrap; gap: 6px; }
  .mr-order-btn { margin-left: auto; }
}
</style>

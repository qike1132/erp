<template>
  <div class="sp-sku-wrap">
    <table class="sp-sku-table">
      <thead>
        <tr>
          <th class="th-cust">客户名称</th>
          <th class="th-prod">产品名称</th>
          <th class="th-code">商品条码</th>
          <th
            v-for="col in SORT_COLS"
            :key="col.key"
            class="th-num th-sortable"
            :aria-sort="sortField === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
            @click="emit('toggle-sort', col.key)"
          >
            <span class="th-inner">
              {{ col.label }}
              <FontAwesomeIcon
                v-if="sortField === col.key"
                :icon="sortDir === 'asc' ? 'sort-up' : 'sort-down'"
                aria-hidden="true"
              />
              <FontAwesomeIcon v-else icon="sort" class="th-sort-muted" aria-hidden="true" />
            </span>
          </th>
          <th class="th-prog">进度</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in rows" :key="`${s.customer_name}|${s.product_name}`" @click="emit('open-detail', { barcode: s.barcode, name: s.product_name, customer: s.customer_name })">
          <td class="td-cust">{{ s.customer_name }}</td>
          <td class="td-prod"><span class="sp-prod">{{ s.product_name }}</span></td>
          <td class="td-code"><span class="sp-code">{{ s.barcode }}</span></td>
          <td class="td-num num">{{ fmt(s.plan_qty) }}</td>
          <td class="td-num num" :class="shippedCls(s)">{{ fmt(s.shipped_qty) }}</td>
          <td class="td-num num" :class="s.remain_qty > 0 ? 'td-remain' : ''">{{ fmt(s.remain_qty) }}</td>
          <td class="td-prog">
            <div class="sp-prog">
              <div class="sp-prog-meter"><i :class="progCls(s._pct)" :style="{ width: s._pct + '%' }" /></div>
              <span class="sp-prog-v num">{{ s._pct }}%</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <UiPagination
      v-if="totalPages > 1"
      :current-page="page"
      :total-pages="totalPages"
      :total-items="totalItems"
      @update:current-page="emit('update:page', $event)"
    />
  </div>
</template>

<script setup lang="ts">
// SKU 月度统计表 —— 从 PurchasePlanMonthlySummary 抽出（原文件加 chips 与分布面板后会破 400 行门禁）。
// 排序/分页/筛选仍由 useSkuSummary 掌管，这里只负责渲染与事件上传。
import UiPagination from '@/components/ui/UiPagination.vue'
import type { SkuRow } from './types'

const props = defineProps<{
  rows: SkuRow[]
  sortField: string
  sortDir: 'asc' | 'desc'
  page: number
  totalPages: number
  totalItems: number
}>()

const emit = defineEmits<{
  'toggle-sort': [field: string]
  'open-detail': [payload: { barcode: string; name: string; customer: string }]
  'update:page': [value: number]
}>()

/** 可排序的三个数字列；字段名与 useSkuSummary 的 fieldMap 对齐 */
const SORT_COLS = [
  { key: 'plan', label: '计划数量' },
  { key: 'shipped', label: '已出货' },
  { key: 'remain', label: '待出货' },
] as const

function fmt(n: number): string {
  return Number(n || 0).toLocaleString('zh-CN')
}

/** 一件未出点红、出完点绿、出了部分点琥珀 —— 只判「是否为 0」会把「出了一点点」也显示成完成 */
function shippedCls(s: SkuRow): string {
  if (Number(s.shipped_qty || 0) <= 0) return 'td-zero'
  if (Number(s.shipped_qty || 0) >= Number(s.plan_qty || 0)) return 'td-done'
  return 'td-part'
}

function progCls(pct: number): string {
  if (pct <= 0) return 'prog-r'
  if (pct < 100) return 'prog-a'
  return 'prog-g'
}
</script>

<style scoped lang="scss">
.sp-sku-wrap {
  border-top: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-sku-table {
  width: 100%;
  border-collapse: collapse;
}

.sp-sku-table thead {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--color-slate-50, #f8fafc);
}

.sp-sku-table th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--color-text-secondary, #475569);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  text-align: left;
  white-space: nowrap;
}

.sp-sku-table td {
  padding: 9px 14px;
  font-size: 13px;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  transition: background 0.2s ease;
}

.sp-sku-table tbody tr {
  cursor: pointer;
}

.sp-sku-table tbody tr:hover td {
  background: var(--color-primary-50);
}

/* 数字列右对齐：左对齐时位数不同的数量无法纵向比大小 */
.th-num,
.td-num {
  text-align: right;
}

.td-zero { color: var(--color-danger-600); font-weight: 700; }
.td-part { color: var(--color-warning-600); font-weight: 700; }
.td-done { color: var(--color-success-600); font-weight: 700; }
.td-remain { color: var(--color-warning-600); font-weight: 700; }

.th-sortable {
  cursor: pointer;
  user-select: none;
}

.th-sortable:hover {
  color: var(--color-primary-500);
}

.th-inner {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.th-sort-muted {
  opacity: 0.25;
}

.th-cust, .td-cust { width: 17%; }
.th-prod, .td-prod { width: 24%; }
.th-code, .td-code { width: 15%; }
.th-prog, .td-prog { width: 16%; }

.td-cust {
  font-weight: 600;
}

.sp-prod {
  font-weight: 600;
  color: var(--color-text);
}

.sp-code {
  font-family: 'SF Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  color: var(--color-text-muted, #94a3b8);
  letter-spacing: 0.03em;
}

.sp-prog {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sp-prog-meter {
  flex: 1;
  min-width: 0;
  max-width: 120px;
  height: 6px;
  border-radius: 3px;
  background: #edf0f6;
  overflow: hidden;
}

.sp-prog-meter > i {
  display: block;
  height: 100%;
  border-radius: 3px;
}

.prog-r { background: var(--color-danger-500, #ea5455); }
.prog-a { background: var(--color-warning-500, #ff9f43); }
.prog-g { background: var(--color-success-500, #28c76f); }

.sp-prog-v {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-muted, #8c96ad);
  min-width: 32px;
}
</style>

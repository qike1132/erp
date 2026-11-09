<template>
  <div class="mp-wrap">
    <table class="mp-grid">
      <colgroup>
        <col style="width:118px" />
        <col style="width:96px" />
        <col style="width:210px" />
        <col style="width:84px" />
        <col style="width:90px" />
        <col style="width:110px" />
        <col style="width:190px" />
        <col style="width:96px" />
        <col style="width:78px" />
        <col style="width:78px" />
        <col style="width:44px" />
        <col style="width:86px" />
        <col style="width:58px" />
      </colgroup>
      <thead>
        <tr>
          <th scope="col">订单号 / 时间</th>
          <th scope="col">客户</th>
          <th scope="col">产品名称</th>
          <th scope="col">订单数量</th>
          <th scope="col">角色</th>
          <th scope="col">供应商</th>
          <th scope="col">物料名称</th>
          <th scope="col">规格型号</th>
          <th scope="col">采购数量</th>
          <th scope="col">已到数量</th>
          <th scope="col">单位</th>
          <th scope="col">进度</th>
          <th scope="col">操作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="order in orders" :key="order.key">
          <tr v-for="(row, idx) in order.rows" :key="row.key">
            <template v-if="idx === 0">
              <td class="mp-order" :rowspan="order.rows.length">
                <div class="mp-order-no">{{ order.orderNo }}</div>
                <div class="mp-order-date">{{ order.poCreateTime || '—' }}</div>
              </td>
              <td :rowspan="order.rows.length">{{ order.customerName || '—' }}</td>
              <td class="mp-product" :rowspan="order.rows.length">
                <div v-for="name in order.productNames" :key="name">{{ name }}</div>
              </td>
              <td class="mp-qty" :rowspan="order.rows.length">{{ order.quantity }}</td>
            </template>

            <td v-if="row.groupFirst" class="mp-role" :rowspan="row.groupSpan">{{ row.roleName }}</td>

            <td v-if="row.groupFirst" class="mp-supplier" :rowspan="row.groupSpan">
              <b>{{ row.supplierName }}</b>
            </td>

            <td class="mp-material">{{ row.materialName }}</td>
            <td>{{ row.specification || '' }}</td>
            <td class="mp-num mp-ordered">{{ row.orderedDisplay }}</td>
            <td class="mp-num mp-received">{{ row.receivedDisplay }}</td>
            <td class="mp-unit">{{ row.unit || '' }}</td>
            <td :class="['mp-pct', row.pctClass]">
              {{ row.progressLabel }}<span v-if="row.overdue" class="mp-overdue-tag">逾期</span>
            </td>

            <td v-if="row.groupFirst" :rowspan="row.groupSpan">
              <button
                type="button"
                class="mp-detail"
                :aria-label="`查看 ${row.supplierName} 的来料明细`"
                @click="emit('view-supplier', row.supplierName, order.orderNo)"
              >
                明细
              </button>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
/**
 * MaterialProgressGrid.vue — 来料进度整页网格表（纯展示）
 *
 * 用户 2026-11-09 定稿：外观与合并方式对齐 /purchase「工厂汇总」表。
 *  · 一行 = 一项物料；订单号/客户/产品名称/订单数量 按整单 rowspan
 *  · 角色 + 供应商按分组合并 rowspan（多角色 SKU 按角色分行），「明细」每组一个入口
 *  · 进度：100% → 到齐，其余 → 百分比；逾期带文字标记，不依赖颜色
 */
import { computed } from 'vue'
import type { ProgressOrderRow, MergedItem } from '../composables/useMaterialRegistrations'
import { formatQuantity } from '@/utils/quantity'

const props = defineProps<{ rows: ProgressOrderRow[] }>()

const emit = defineEmits<{
  'view-supplier': [supplierName: string, orderNo: string]
}>()

interface FlatRow {
  key: string
  groupFirst: boolean
  groupSpan: number
  roleName: string
  supplierName: string
  materialName: string
  specification: string
  receivedDisplay: string
  orderedDisplay: string
  unit: string
  progressLabel: string
  pctClass: string
  overdue: boolean
}

interface OrderBlock {
  key: string
  orderNo: string
  poCreateTime: string
  customerName: string
  productNames: string[]
  quantity: string
  rows: FlatRow[]
}

/** 已到齐：有采购量且已到 ≥ 采购 */
function isDone(item: MergedItem): boolean {
  return item.ordered_quantity > 0 && item.received_quantity >= item.ordered_quantity
}

/** 进度四档：逾期 > 已到齐 > 未到 > 进行中（与图例口径一致） */
function pctClass(item: MergedItem): string {
  if (item.overdue) return 'is-overdue'
  if (isDone(item)) return 'is-done'
  if (item.received_quantity <= 0) return 'is-zero'
  return 'is-ongoing'
}

/** 100% 写「到齐」，其余一律百分比（0% 不再用「未到」文案） */
function progressLabel(item: MergedItem): string {
  if (isDone(item)) return '到齐'
  return `${item.progress}%`
}

const orders = computed<OrderBlock[]>(() =>
  props.rows.map((order) => {
    const productNames = order.skuItems && order.skuItems.length > 1
      ? order.skuItems.map((s) => s.product_name).filter(Boolean)
      : [order.productName || '—']

    const rows: FlatRow[] = []
    for (const group of order.groups) {
      group.items.forEach((item, i) => {
        rows.push({
          key: `${group.roleName}|${group.supplierName}|${item.material_name}|${i}`,
          groupFirst: i === 0,
          groupSpan: group.items.length,
          roleName: group.roleName,
          supplierName: group.supplierName,
          materialName: item.material_name,
          specification: item.specification || '',
          receivedDisplay: item.received_display,
          orderedDisplay: item.ordered_display,
          unit: item.unit || '',
          progressLabel: progressLabel(item),
          pctClass: pctClass(item),
          overdue: item.overdue,
        })
      })
    }

    return {
      key: order.orderNo,
      orderNo: order.orderNo,
      poCreateTime: order.poCreateTime,
      customerName: order.customerName,
      productNames: productNames.length ? productNames : [order.productName || '—'],
      quantity: order.productQuantity != null ? formatQuantity(order.productQuantity) : '—',
      rows,
    }
  }),
)
</script>

<style scoped lang="scss">
.mp-wrap {
  overflow-x: auto;
  padding: 12px 16px 4px;
}

.mp-grid {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 12.5px;
}

.mp-grid th,
.mp-grid td {
  border: 1px solid var(--color-border, #cfd6e2);
  padding: 8px 6px;
  text-align: center;
  vertical-align: middle;
  line-height: 1.35;
  word-break: break-all;
}

.mp-grid th {
  background: #f2f4f8;
  font-weight: 700;
  color: var(--color-text, #1a1a2e);
  font-size: 12.5px;
  white-space: nowrap;
}

.mp-order { white-space: nowrap; }
.mp-order-no {
  font-weight: 700;
  color: var(--color-primary-700, #2d5ab8);
  font-variant-numeric: tabular-nums;
}
.mp-order-date {
  font-size: 11px;
  color: var(--color-text-muted, #64748b);
  font-variant-numeric: tabular-nums;
  margin-top: 2px;
}

.mp-product { text-align: left; }
.mp-product div + div { margin-top: 2px; }

.mp-qty {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.mp-role { color: var(--color-text-secondary, #475569); font-weight: 600; }
.mp-supplier b { font-weight: 700; }

.mp-material { text-align: left; }

.mp-num { font-variant-numeric: tabular-nums; }
.mp-received { font-weight: 700; }
.mp-ordered { color: var(--color-text-secondary, #475569); }

.mp-unit { color: var(--color-text-muted, #64748b); }

.mp-pct {
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  white-space: nowrap;
}
.mp-pct.is-ongoing { color: #3a6bd6; }
.mp-pct.is-done { color: #1e9e55; }
.mp-pct.is-zero { color: #9a6a00; }
.mp-pct.is-overdue { color: #c0392b; }

.mp-overdue-tag {
  display: inline-block;
  font-size: 10.5px;
  font-weight: 700;
  color: #b3261e;
  background: #fdeaea;
  border-radius: 999px;
  padding: 0 6px;
  margin-left: 3px;
}

.mp-detail {
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--color-primary-600, #3a6bd6);
  background: #fff;
  border: 1px solid #cfdcf6;
  border-radius: 6px;
  padding: 3px 8px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}
.mp-detail:hover { background: #eef4ff; border-color: #a9c2ee; }
.mp-detail:focus-visible { outline: 2px solid var(--color-primary-600, #3a6bd6); outline-offset: 1px; }
</style>

<template>
  <UiDialog :open="open" :max-width-class="'max-w-[1100px]'" @update:open="$emit('close')">
    <div v-if="order" class="odm-body">
      <!-- 物料清单 -->
      <div class="odm-section">
        <div class="odm-section-title">
          <FontAwesomeIcon icon="list" aria-hidden="true" />
          <span>物料清单</span>
          <span v-if="(order.items || []).length > 0" class="odm-section-count">{{ (order.items || []).length }} 项</span>
        </div>
        <div class="odm-table-wrap">
          <table class="odm-table">
            <thead>
              <tr>
                <th class="odm-w-name">物料名称</th>
                <th class="odm-w-spec">规格</th>
                <th class="odm-th-num">数量</th>
                <th class="odm-w-unit">单位</th>
                <th class="odm-w-source">来源</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, idx) in order.items || []" :key="idx">
                <td class="odm-td-name">{{ item.material_name || '—' }}</td>
                <td class="odm-td-muted">{{ item.specification || '—' }}</td>
                <td class="odm-td-num">{{ formatNumber(displayQty(item)) }}</td>
                <td class="odm-td-muted">{{ item.unit || '—' }}</td>
                <td class="odm-td-muted">{{ scopeOf(item) }}</td>
              </tr>
              <tr v-if="(order.items || []).length === 0">
                <td colspan="5" class="odm-td-empty">暂无物料数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <template #footer>
      <button class="odm-close" aria-label="关闭" @click="$emit('close')">
        关闭
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import UiDialog from '@/components/ui/UiDialog.vue'
import type { PurchaseOrder, PurchaseOrderItem } from '@/types'
import { formatNumber } from '@/utils/format'
import { factoryQtyDisplayValue } from '../composables/useSummaryModal'

const props = defineProps<{
  open: boolean
  order: PurchaseOrder | null
}>()

/**
 * 物料清单「数量」列的展示值：与「汇总下单 → 工厂内部采购订单汇总」的数量列**同源**。
 *
 * 口径 = 原始落库数量按该行损耗率（千分之几）加放后向上取整，
 * 即最终确认的采购数量；用户自定义调整损耗率后，这里立刻反映同一数值。
 *
 * 损耗率回退链（与 useSummaryModal 的逐行播种口径一致）：
 * 逐行 loss_rate → 订单级 spare_rate → 0（旧数据零回归，等于原始落库数量）。
 * 只做展示派生，**不写回任何数据**。
 */
function displayQty(item: PurchaseOrderItem): number {
  const baseQty = parseFloat(String(item.quantity)) || 0
  const itemRate = item.loss_rate
  const orderRate = props.order?.spare_rate
  const rate = typeof itemRate === 'number' && Number.isFinite(itemRate)
    ? itemRate
    : typeof orderRate === 'number' && Number.isFinite(orderRate)
      ? orderRate
      : 0
  return factoryQtyDisplayValue(baseQty, rate, false)
}

defineEmits<{ close: [] }>()

/** 明细的来源 BOM 作用域：一键生成会写 '来源BOM：<默认BOM|角色名>' 到 remark。
 *  无该前缀时回退到备注原文（手工备注），都没有则显示 '—'。 */
function scopeOf(item: { remark?: string | null }): string {
  const remark = (item.remark || '').trim()
  if (!remark) return '—'
  const prefix = '来源BOM：'
  return remark.startsWith(prefix) ? remark.slice(prefix.length) : remark
}
</script>

<style scoped>
/* ============ 设计令牌（与 CompletedOrdersPanel 一致） ============ */
.odm-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  font-family: var(--font-sans);
  color: #0f172a;
}

/* ============ 物料清单 section ============ */
.odm-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.odm-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
}

.odm-section-title i {
  color: var(--color-primary-700, #2d5ab8);
  font-size: 12px;
}

.odm-section-count {
  margin-left: 4px;
  padding: 1px 6px;
  border-radius: 3px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
}

/* ============ 表格 ============ */
.odm-table-wrap {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  overflow: auto;
  max-height: 560px;
}

.odm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  /* fixed 布局：列宽完全由 th 的 width 决定，确保表头与数据列宽一致 */
  table-layout: fixed;
}

.odm-table thead th {
  padding: 10px 12px;
  text-align: left;
  font-weight: 600;
  font-size: 11px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}

/* 数量列：表头与数据统一居中。
   注意 `.odm-table thead th`（0,2,1）的 text-align:left 特异性高于 `.odm-th-num`（0,1,0），
   故这里显式提权，否则表头仍会左对齐、与数据列错位。 */
.odm-table thead th.odm-th-num,
.odm-table tbody td.odm-td-num {
  text-align: center;
}

.odm-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid #f1f5f9;
  color: #0f172a;
  vertical-align: middle;
}

.odm-table tbody tr:hover td {
  background: var(--color-primary-50, #eff5ff);
}

/* 列宽分配：物料名称主导，规格次之，数量/单位紧凑，来源兜底（总和 100%）
   fixed 布局下列宽由 th 决定，表头与数据严格对齐 */
.odm-w-name { width: 38%; }
.odm-w-spec { width: 24%; }
.odm-th-num { width: 14%; }
.odm-w-unit { width: 8%; }
.odm-w-source { width: 16%; }

.odm-td-name {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.odm-td-muted {
  color: #64748b;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.odm-td-num {
  font-weight: 600;
  color: var(--color-primary-700, #2d5ab8);
  white-space: nowrap;
}

.odm-td-empty {
  text-align: center;
  color: #94a3b8;
  padding: 32px 12px !important;
  font-size: 13px;
}

/* ============ 关闭按钮 ============ */
.odm-close {
  padding: 7px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  background: #fff;
  color: #475569;
  font-family: inherit;
}

.odm-close:hover {
  border-color: var(--color-primary-500, #5b8def);
  color: var(--color-primary-700, #2d5ab8);
  background: var(--color-primary-50, #eff5ff);
}
</style>

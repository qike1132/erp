<template>
  <div class="mr-content">
    <div class="mr-card">
      <div class="mr-card-b mr-card-b--flush">
        <div v-if="pIsFetching && progressRows.length" class="mr-fetching-bar"><div class="mr-fetching-progress" /></div>
        <UiDataTable
          :data="progressOrderRows"
          :columns="progressColumns"
          :loading="pIsLoading && !progressRows.length"
          :paginator="true"
          :rows="pPerPage"
          :total-records="pPages * pPerPage"
          row-key="order_no"
          @page="emit('page', $event)"
        >
          <template #empty>
            <div class="mr-empty"><FontAwesomeIcon icon="inbox" /><span>暂无进行中的来料登记</span></div>
          </template>
          <template #column-body-po_create_time="{ row }">
            <span class="mr-td-date">{{ row.po_create_time || '-' }}</span>
          </template>
          <template #column-body-customer_name="{ row }">
            {{ row.customer_name || '-' }}
          </template>
          <template #column-body-product_name="{ row }">
            <template v-if="row.sku_items && row.sku_items.length > 1">
              <div v-for="(sku, idx) in row.sku_items" :key="sku.barcode || sku.product_name || idx" class="mr-sku-line">{{ sku.product_name || '-' }}</div>
            </template>
            <span v-else class="mr-order-link">{{ row.product_name || '-' }}</span>
          </template>
          <template #column-body-product_quantity="{ row }">
            <span class="mr-td-qty">
              <template v-if="row.sku_items && row.sku_items.length > 1">
                <div v-for="(sku, idx) in row.sku_items" :key="sku.barcode || sku.product_name || idx" class="mr-sku-line">{{ sku.quantity != null ? sku.quantity : '-' }}</div>
              </template>
              <template v-else>{{ row.product_quantity != null ? row.product_quantity : '-' }}</template>
            </span>
          </template>
          <template #column-body-groupedItems="{ row }">
            <div class="mr-supplier-groups">
              <div v-for="grp in row.groupedItems" :key="grp.supplierName" class="mr-supplier-group">
                <div class="mr-supplier-label" @click="toggleExpand(row.order_no + '|' + grp.supplierName)"><FontAwesomeIcon icon="truck" /><span>{{ grp.supplierName || '未指定' }}</span><span class="mr-supplier-count">{{ grp.items.length }} 项</span><span class="mr-expand-icon">{{ expandedGroups.has(row.order_no + '|' + grp.supplierName) ? '▼' : '▶' }}</span></div>
                <div v-if="expandedGroups.has(row.order_no + '|' + grp.supplierName)" class="mr-items-container">
                  <div v-for="i in grp.items" :key="i.material_name" class="mr-list-item-row">
                    <span class="mr-list-item-name" :title="i.material_name">{{ i.material_name }}</span>
                    <span class="mr-list-item-qty">数量:<b>{{ i.ordered_display }}</b></span>
                    <span class="mr-list-item-rcv">已到货:<b>{{ i.received_display }}</b></span>
                    <div class="mr-list-item-bar"><div :class="['mr-sku-fill', fillClass(i)]" :style="{ width: (i.progress || 0) + '%', height: '100%', borderRadius: '5px' }" /></div>
                    <span class="mr-list-item-pct">{{ i.progress || 0 }}%</span>
                  </div>
                </div>
              </div>
            </div>
          </template>
          <template #column-body-progress="{ row }">
            <div class="mr-pbar-wrap"><div class="mr-pbar"><div :class="['mr-pfill', row.progress >= 100 ? 'completed' : 'pending']" :style="{ width: (row.progress || 0) + '%' }" /></div><span class="mr-pbar-pct">{{ row.progress || 0 }}%</span></div>
          </template>
          <template #column-body-actions="{ row }">
            <div class="mr-action-group"><button type="button" class="mr-action-btn mr-action-view" title="查看供应商详情" aria-label="查看供应商详情" @click="emit('view-supplier', row.supplier_name || '', row.order_no)"><FontAwesomeIcon icon="eye" /></button></div>
          </template>
        </UiDataTable>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 来料进度 Tab（从 MaterialView.vue 抽出，模板原样搬移）
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { Registration } from '@/api/material'
import type { ProgressOrderRow } from '../composables/useMaterialRegistrations'
import { reactive } from 'vue'

defineProps<{
  progressOrderRows: ProgressOrderRow[]
  progressRows: Registration[]
  pIsLoading: boolean
  pIsFetching: boolean
  pPerPage: number
  pPages: number
}>()

const emit = defineEmits<{
  page: [event: { page: number; rows: number }]
  'view-supplier': [supplierName: string, orderNo: string]
}>()

function fillClass(item: { progress?: number; received_quantity: number | string; ordered_quantity: number | string }) { const pct = item.progress || 0; if (pct >= 100 || Number(item.received_quantity) >= Number(item.ordered_quantity)) return 'full'; return 'low' }

// 方案2：供应商分组默认折叠，点击展开才渲染物料明细，大幅减少初始 DOM 节点
const expandedGroups = reactive(new Set<string>())
function toggleExpand(key: string) {
  if (expandedGroups.has(key)) expandedGroups.delete(key)
  else expandedGroups.add(key)
}

/** UiDataTable 列定义 */
const progressColumns: TableColumn[] = [
  { field: 'po_create_time', header: '订单时间', width: '110px', align: 'center' },
  { field: 'customer_name', header: '客户', width: '120px', align: 'center' },
  { field: 'product_name', header: '产品名称', align: 'left' },
  { field: 'product_quantity', header: '订单数量', width: '100px', align: 'center' },
  { field: 'groupedItems', header: '物料进度（按供应商分组）', align: 'left' },
  { field: 'progress', header: '总进度', width: '200px', align: 'center' },
  { field: 'actions', header: '操作', width: '80px', align: 'center' },
]
</script>

<style scoped lang="scss">
/* === Content area === */
.mr-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 24px 24px;
}

/* === Cards === */
.mr-card {
  background: white;
  border-radius: 14px;
  margin-bottom: 18px;
  overflow: hidden;
}

.mr-card-b {
  padding: 24px;
}

.mr-card-b--flush {
  padding: 0;
  overflow-x: auto;
}

/* 每个订单（行）之间显示分割线 */
.mr-card-b--flush :deep(.p-datatable-tbody > tr) {
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.mr-order-link {
  font-size: 14px;
  color: var(--color-text);
}

.mr-sku-line {
  font-size: 14px;
  color: var(--color-text);
  padding: 2px 0;
  line-height: 1.4;
}
.mr-sku-line + .mr-sku-line {
  border-top: 1px dashed var(--color-border, #e5e7eb);
}

.mr-td-qty {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.mr-td-date {
  font-size: 13px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

/* 供应商分组容器 */
.mr-supplier-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mr-supplier-group {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 6px;
  background: var(--color-surface, #f8fafc);
  overflow: hidden;
}

.mr-supplier-label {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--color-primary-50, #eff6ff);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-700, #1d4ed8);
  cursor: pointer;
  user-select: none;
}

.mr-supplier-label i {
  font-size: 11px;
}

.mr-supplier-count {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-muted, #94a3b8);
}

.mr-expand-icon {
  margin-left: 4px;
  font-size: 10px;
  color: var(--color-text-muted, #94a3b8);
  flex-shrink: 0;
}

.mr-supplier-group .mr-items-container {
  padding: 4px 8px;
  background: white;
}

/* === Item List === */
.mr-items-container { min-width: 500px; }

.mr-list-item-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background 0.15s ease;
}

.mr-list-item-row:last-child { margin-bottom: 0; }
.mr-list-item-row:hover { background: var(--color-primary-50, #eff6ff); }

.mr-list-item-name { font-size: 13px; width: 140px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; flex-shrink: 0; }
.mr-list-item-qty { font-size: 12px; color: var(--color-text-secondary); white-space: nowrap; width: 105px; flex-shrink: 0; }
.mr-list-item-rcv { font-size: 12px; color: var(--color-success-600, #059669); white-space: nowrap; width: 115px; flex-shrink: 0; }
.mr-list-item-bar { flex: 1; height: 10px; background: #E5E7EB; border-radius: 8px; min-width: 60px; }
.mr-list-item-pct { font-size: 12px; color: var(--color-text-muted); width: 50px; flex-shrink: 0; text-align: right; }

/* === Progress Bar === */
.mr-pbar-wrap { display: flex; align-items: center; gap: 8px; }

.mr-pbar { width: 160px; height: 10px; background: #E5E7EB; border-radius: 8px; overflow: hidden; }

.mr-pfill { height: 100%; border-radius: 8px; transition: width 0.5s ease; }
.mr-pfill.pending { background: var(--color-warning-500, #FF9F43); }
.mr-pfill.partial { background: var(--color-warning-500, #FF9F43); }
.mr-pfill.completed { background: var(--color-success-500, #28C76F); }

.mr-pbar-pct { font-size: 13px; color: var(--color-text-secondary); }

/* === Action Buttons === */
.mr-action-group { display: flex; gap: 6px; }

.mr-action-btn {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  transition: all 0.2s ease;
  cursor: pointer;
}

.mr-action-view {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.mr-action-view:hover {
  background: var(--color-primary-500);
  color: white;
  transform: translateY(-1px);
}

/* === SKU Fill Colors === */
.mr-sku-fill.full { background: var(--color-success-500, #28C76F); }
.mr-sku-fill.half { background: var(--color-primary-500, #5B8DEF); }
.mr-sku-fill.low { background: var(--color-warning-500, #FF9F43); }
.mr-sku-fill.zero { background: #E5E7EB; }

/* === Empty State === */
.mr-empty {
  text-align: center;
  padding: 40px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.mr-empty i { font-size: 28px; opacity: 0.5; }

/* Fetching progress bar */
.mr-fetching-bar {
  padding: 0 !important;
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
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
</style>

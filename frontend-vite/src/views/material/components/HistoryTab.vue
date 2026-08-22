<template>
  <div class="mr-content">
    <div class="mr-card">
      <div class="mr-card-b mr-card-b--flush">
        <div v-if="hIsFetching && hRegistrations.length" class="mr-fetching-bar"><div class="mr-fetching-progress" /></div>
        <UiDataTable
          :data="hRegistrations"
          :columns="historyColumns"
          :loading="hIsLoading && !hRegistrations.length"
          :paginator="true"
          :rows="hPerPage"
          :total-records="hPages * hPerPage"
          row-key="id"
          @page="emit('page', $event)"
        >
          <template #empty>
            <div class="mr-empty"><FontAwesomeIcon icon="archive" /><span>暂无历史记录</span></div>
          </template>
          <template #column-body-purchase_order_no="{ row }">
            <span class="mr-td-order">{{ (row as Registration).purchase_order_no }}</span>
          </template>
          <template #column-body-customer_name="{ row }">
            {{ (row as Registration).customer_name || '-' }}
          </template>
          <template #column-body-product="{ row }">
            <span class="mr-td-small">{{ (row as Registration).product_name || '-' }}{{ (row as Registration).product_quantity ? ' x' + (row as Registration).product_quantity : '' }}</span>
          </template>
          <template #column-body-supplier_name="{ row }">
            {{ (row as Registration).supplier_name || '-' }}
          </template>
          <template #column-body-materials="{ row }">
            <span class="mr-td-small">{{ materialSummary(row as Registration) }}</span>
          </template>
          <template #column-body-update_time="{ row }">
            <span class="mr-td-small mr-td-muted">{{ (row as Registration).update_time || '-' }}</span>
          </template>
          <template #column-body-actions="{ row }">
            <div class="mr-action-group"><button type="button" class="mr-action-btn mr-action-view" title="查看详情" aria-label="查看详情" @click="emit('view-detail', (row as Registration).id)"><FontAwesomeIcon icon="eye" /></button></div>
          </template>
        </UiDataTable>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// 历史查询 Tab（从 MaterialView.vue 抽出，模板原样搬移）
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { Registration } from '@/api/material'

defineProps<{
  hRegistrations: Registration[]
  hIsLoading: boolean
  hIsFetching: boolean
  hPerPage: number
  hPages: number
}>()

const emit = defineEmits<{
  page: [event: { page: number; rows: number }]
  'view-detail': [id: number]
}>()

/** 拼接历史记录的物料名称摘要 */
function materialSummary(r: Registration) {
  const items = r.items || []
  if (!items.length) return '-'
  return items.map(i => i.material_name).join(', ')
}

/** UiDataTable 列定义 */
const historyColumns: TableColumn[] = [
  { field: 'purchase_order_no', header: '订单号', width: '150px', align: 'center' },
  { field: 'customer_name', header: '客户', width: '100px', align: 'center' },
  { field: 'product', header: '产品/数量', width: '120px', align: 'center' },
  { field: 'supplier_name', header: '供应商', width: '100px', align: 'center' },
  { field: 'materials', header: '物料名称', align: 'left' },
  { field: 'update_time', header: '完成时间', width: '120px', align: 'center' },
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

/* === Table === */
.mr-td-order { font-family: 'Courier New', monospace; font-weight: 600; color: var(--color-primary-500); font-size: 14px; }
.mr-td-small { font-size: 13px; }
.mr-td-muted { color: var(--color-text-muted); }

/* 每个订单（行）之间显示分割线 */
.mr-card-b--flush :deep(.p-datatable-tbody > tr) {
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

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

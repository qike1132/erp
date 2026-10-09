<template>
  <div class="sr-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <button
          v-if="canManage"
          class="sr-action-btn sr-action-btn-primary"
          aria-label="新增退货"
          @click="openStandalone"
        >
          <FontAwesomeIcon icon="plus" aria-hidden="true" /> 新增退货
        </button>
        <div class="page-toolbar-right">
          <div class="sr-filter-row">
            <input v-model="startDate" type="date" class="sr-date-input" aria-label="开始日期" @change="applyFilter" />
            <span class="sr-date-sep">~</span>
            <input v-model="endDate" type="date" class="sr-date-input" aria-label="结束日期" @change="applyFilter" />
            <UiSearchInput v-model="searchTerm"
                           placeholder="搜索客户名称..."
                           @update:model-value="onSearchInput"
                           @clear="clearSearch"
            />
          </div>
        </div>
      </div>

      <div class="sr-info-bar">
        <span>共 <b>{{ totalItems }}</b> 条退货记录</span>
        <template v-if="startDate || endDate">
          <span class="sep" />
          <span>日期 {{ startDate || '…' }} ~ {{ endDate || '…' }}</span>
        </template>
        <template v-if="debouncedVisible">
          <span class="sep" />
          <span>客户「{{ debouncedVisible }}」</span>
        </template>
        <button class="sr-reset-btn" @click="clearSearch">重置筛选</button>
      </div>

      <div class="sr-content">
        <UiDataTable
          :data="returns"
          :columns="columns"
          :loading="isLoading"
          paginator
          :rows="perPage"
          :total-records="totalItems"
          :current-page="currentPage"
          :page-size-options="[]"
          hide-paginator-on-single-page
          row-key="id"
          empty-message="暂无退货记录"
          @page="onPage"
        >
          <template #column-body-return_no="{ row }">
            <span class="sr-mono">{{ (row as StockReturnRow).return_no }}</span>
          </template>
          <template #column-body-product="{ row }">
            {{ (row as StockReturnRow).product?.name || '-' }}
          </template>
          <template #column-body-quantity="{ row }">
            {{ (row as StockReturnRow).quantity }}
          </template>
          <template #column-body-stockout_no="{ row }">
            <span class="sr-mono dim">{{ (row as StockReturnRow).stockout_no || '-' }}</span>
          </template>
          <template #column-body-reason="{ row }">
            <span :title="(row as StockReturnRow).note || undefined" class="sr-reason">
              {{ (row as StockReturnRow).reason || '-' }}
            </span>
          </template>
          <template #column-body-status="{ row }">
            <span
              class="badge"
              :class="(row as StockReturnRow).status === 'cancelled' ? 'badge-cancelled' : 'badge-active'"
            >
              {{ (row as StockReturnRow).status === 'cancelled' ? '已取消' : '正常' }}
            </span>
          </template>
          <template v-if="canEdit || canDelete" #column-body-actions="{ row }">
            <StockReturnRowActions
              :row="row as StockReturnRow"
              :can-edit="canEdit"
              :can-delete="canDelete"
              :disabled="actionId === (row as StockReturnRow).id"
              @edit="openReturnEdit"
              @delete="handleDelete"
            />
          </template>
        </UiDataTable>
      </div>
    </div>

    <StockReturnCreateDialog
      v-model:form="form"
      v-model:search-keyword="searchKeyword"
      :open="formOpen"
      :submitting="submitting"
      :shipments="shipments"
      :loading-shipments="loadingShipments"
      @update:open="formOpen = $event"
      @search="searchShipments"
      @pick="pickShipment"
      @submit="handleSubmit"
    />

    <EditReturnModal
      v-model:form="returnEditForm"
      :open="returnEditVisible"
      :saving="savingReturn"
      :save-return-edit="saveReturnEdit"
      @update:open="returnEditVisible = $event"
    />

    <UiConfirmDialog
      :open="confirmDialog.open"
      :text="confirmDialog.text"
      :sub="confirmDialog.sub"
      :type="confirmDialog.type"
      @confirm="confirmDialog.onConfirm"
      @cancel="confirmDialog.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * StockReturnView.vue — 退货管理页面
 *
 * 职责：
 * - 退货列表（服务端分页 + 客户搜索/日期区间筛选；P1-① 含状态列）
 * - 新增退货：页内选可退出货单（仅独立出货，备货抵扣行不参与退货），或从库存出货列表行内发起
 * - 取消退货（P1-① 软取消：记录保留、库存对称扣回，stock_return_manage 权限）
 * - 信息条为单行 40px 汇总（约定：不做大卡片统计区）
 */
import { computed } from 'vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import UiSearchInput from '@/components/ui/UiSearchInput.vue'
import { useAuthStore } from '@/stores/auth'
import type { StockReturnRecord } from '@/api/stockReturn'
import StockReturnCreateDialog from './components/StockReturnCreateDialog.vue'
import StockReturnRowActions from './components/StockReturnRowActions.vue'
import EditReturnModal from '@/views/report/components/EditReturnModal.vue'
import { useStockReturn } from './composables/useStockReturn'

type StockReturnRow = StockReturnRecord

const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('stock_return_manage'))
// 行内操作各自独立授权，且镜像后端 require_any_permission 的口径
// （PUT/DELETE 均接受 stock_return_manage 或对应子码 return_edit/return_delete）——
// 只授模块管理码的用户同样能操作，避免前端把后端允许的动作藏起来。
const canEdit = computed(
  () => auth.hasPermission('stock_return_manage') || auth.hasPermission('return_edit'),
)
const canDelete = computed(
  () => auth.hasPermission('stock_return_manage') || auth.hasPermission('return_delete'),
)

const {
  confirmDialog,
  actionId,
  searchTerm,
  startDate,
  endDate,
  currentPage,
  perPage,
  onSearchInput,
  clearSearch,
  applyFilter,
  isLoading,
  returns,
  totalItems,
  goPage,
  debouncedSearch,
  formOpen,
  form,
  searchKeyword,
  shipments,
  loadingShipments,
  searchShipments,
  pickShipment,
  submitting,
  openStandalone,
  handleSubmit,
  handleDelete,
  returnEditVisible,
  returnEditForm,
  savingReturn,
  openReturnEdit,
  saveReturnEdit,
} = useStockReturn()

/** 信息条展示用：防抖后的客户关键字（searchTerm 是输入框实时值） */
const debouncedVisible = debouncedSearch

/** UiDataTable 分页事件（0 基页码）→ 服务端分页 goPage（1 基），与 SupplierTable 同构 */
function onPage(event: { page: number }) {
  goPage(event.page + 1)
}

const actionsColumn: TableColumn = { field: 'actions', header: '操作', align: 'center', width: '110px' }

const columns: TableColumn[] = [
  { field: 'return_no', header: '退货编号', align: 'left', width: '160px' },
  { field: 'return_date', header: '退货日期', align: 'left', width: '110px' },
  { field: 'customer', header: '客户', align: 'left', width: '130px' },
  { field: 'product', header: '产品', align: 'left', width: '170px' },
  { field: 'quantity', header: '数量', align: 'right', width: '80px' },
  { field: 'stockout_no', header: '关联出货单号', align: 'left', width: '160px' },
  { field: 'reason', header: '退货原因', align: 'left' },
  { field: 'status', header: '状态', align: 'center', width: '90px' },
  ...(canEdit.value || canDelete.value ? [actionsColumn] : []),
]
</script>

<style scoped>
/* 本页卡片直角（对齐 /purchase、/supplier 方正基准）：scoped 未分层样式
   优先于 @layer components 里的全局 18px 圆角，仅影响 /stock-return */
.page-card {
  border-radius: 0;
}

.sr-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.sr-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light);
  border-radius: 0;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease;
  color: var(--color-text);
}
.sr-action-btn-primary {
  color: var(--color-primary-600);
}
.sr-action-btn-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
}

.sr-filter-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sr-date-input {
  height: 34px;
  padding: 0 8px;
  border: 1px solid var(--color-border, #e4e7ed);
  font-size: 12px;
  color: var(--color-text);
  background: white;
}
.sr-date-input:focus {
  outline: none;
  border-color: var(--color-primary-300);
}
.sr-date-sep {
  color: var(--color-text-muted);
}

/* 一行信息条（~40px）：汇总用，不做大卡片统计区 */
.sr-info-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 40px;
  padding: 0 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  font-size: 13px;
  color: var(--color-text-secondary);
}
.sr-info-bar b {
  color: var(--color-primary-700);
}
.sr-info-bar .sep {
  width: 1px;
  height: 14px;
  background: var(--color-border, #e4e7ed);
}
.sr-reset-btn {
  margin-left: auto;
  border: none;
  background: none;
  color: var(--color-primary-600);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  padding: 0;
}
.sr-reset-btn:hover {
  text-decoration: underline;
}

.sr-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.sr-mono {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--color-primary-700);
}
.sr-mono.dim {
  color: var(--color-text-secondary);
}
.sr-reason {
  cursor: default;
}
.badge {
  display: inline-block;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid;
}
.badge-active {
  background: var(--color-success-50, #e8f9ef);
  color: var(--color-success-700, #2e7d32);
  border-color: var(--color-success-200, #a6e8c0);
}
.badge-cancelled {
  background: var(--color-border-light, #f0f2f5);
  color: var(--color-text-muted, #64748b);
  border-color: var(--color-border, #e4e7ed);
}
</style>

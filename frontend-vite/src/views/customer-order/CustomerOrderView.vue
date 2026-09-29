<template>
  <div class="co-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="co-tab-bar">
          <button :class="['co-tab-btn', activeTab === 'input' && 'active']" aria-label="录入" @click="activeTab = 'input'">
            录入
          </button>
          <button :class="['co-tab-btn', activeTab === 'records' && 'active']" aria-label="记录查询" @click="activeTab = 'records'">
            记录查询
          </button>
        </div>
      </div>

      <!-- TAB: 录入 -->
      <div v-show="activeTab === 'input'" class="co-tab-content">
        <div class="page-card-body">
          <!-- 左栏：录入表单 -->
          <OrderInputPanel
            ref="inputPanelRef"
            v-model:is-drag-over="isDragOver"
            v-model:form="form"
            :is-order="isOrder"
            :customer-options="customerOptions"
            :missing-fields="missingFields"
            :available-stock="availableStock"
            :stock-error="stockError"
            :deduct-info-visible="deductInfoVisible"
            :excel-file="excelFile"
            :importing="importing"
            :search-products="searchProducts"
            :product-search-failed="productSearchFailed"
            :select-product="selectProduct"
            :handle-deduct-preview="handleDeductPreview"
            :open-deduct-edit="openDeductEdit"
            :handle-excel-select="handleExcelSelect"
            :on-drop="onDrop"
            :download-template="downloadTemplate"
            :handle-import="handleImport"
            :add-staged-items="addStagedItems"
            @add-staged="addStaged"
          />

          <!-- 右栏：暂存列表 + 提交按钮 -->
          <StagingArea
            :staged-items="stagedItems"
            :submitting="submitting"
            @edit-staged="openEditStaged"
            @remove-staged="removeStagedItem"
            @submit-all="submitAll"
          />
        </div>
      </div>

      <!-- TAB: 记录查询 -->
      <div v-show="activeTab === 'records'" class="co-tab-content">
        <OrderRecordQuery
          v-model:per-page="perPage"
          v-model:show-filter="showFilter"
          v-model:filter-customer="filterCustomer"
          v-model:filter-status="filterStatus"
          v-model:filter-factory="filterFactory"
          v-model:filter-start="filterStart"
          v-model:filter-end="filterEnd"
          :record-type="recordType"
          :record-type-options="recordTypeOptions"
          :customer-options="customerOptions"
          :factory-options="factoryOptions"
          :factory-disabled="factoryDisabled"
          :status-options="statusOptions"
          :order-records="orderRecords"
          :is-loading-records="isLoadingRecords"
          :is-fetching-records="isFetchingRecords"
          :error-message="errorMessage"
          :current-page="currentPage"
          :total-pages="totalPages"
          :total-records="totalRecords"
          :can-delete="canDelete"
          :fetch-orders="fetchOrders"
          :reset-filter="resetFilter"
          @change-record-type="handleChangeRecordType"
          @view-detail="openDetail"
          @delete-record="handleDeleteOrder"
          @change-page="handleChangePage"
          @retry="fetchOrders"
        />
      </div>

    </div>

    <!-- 订单详情弹窗 -->
    <EditOrderModal v-model:open="detailOpen"
                    v-model:edit-form="editForm"
                    :detail-data="detailData"
                    :available-stockin="availableStockin"
                    :saving="saving"
                    :deduct-retry-pending="deductRetryPending"
                    :get-status-class="getStatusClass"
                    :save-edit-order="saveEditOrder"
                    :retry-deduct-update="retryDeductUpdate"
    />

    <!-- 编辑暂存弹窗 -->
    <EditStagedModal
      v-model:open="editStagedVisible"
      v-model:edit-staged-data="editStagedData"
      :edit-available-stock="editAvailableStock"
      :customer-options="customerOptions"
      :save-edit-staged="saveEditStaged"
    />

    <!-- 确认对话框 -->
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
import { ref, watch, nextTick, computed } from 'vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { showToast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { QUANTITY_RANGE_MESSAGE } from './composables/quantityRange'
import { useOrderForm } from './composables/useOrderForm'
import { useOrderList } from './composables/useOrderList'
import { useOrderActions } from './composables/useOrderActions'
import type { StagedItem } from './composables/types'

import OrderInputPanel from './components/OrderInputPanel.vue'
import StagingArea from './components/StagingArea.vue'
import OrderRecordQuery from './components/OrderRecordQuery.vue'
import EditOrderModal from './components/EditOrderModal.vue'
import EditStagedModal from './components/EditStagedModal.vue'

const {
  form,
  isOrder,
  missingFields,
  quantityOutOfRange,
  customerOptions,
  searchProducts,
  productSearchFailed,
  selectProduct,
  availableStock,
  deductInfoVisible,
  stockError,
  handleDeductPreview,
  openDeductEdit,
  resetFormAfterAdd,
} = useOrderForm()

/** 录入面板引用：新增成功后把焦点交回产品输入框 */
const inputPanelRef = ref<InstanceType<typeof OrderInputPanel> | null>(null)

const {
  showFilter,
  filterCustomer,
  filterStatus,
  filterFactory,
  filterStart,
  filterEnd,
  currentPage,
  perPage,
  totalPages,
  isLoadingRecords,
  isFetchingRecords,
  errorMessage,
  totalRecords,
  orderRecords,
  recordType,
  recordTypeOptions,
  factoryOptions,
  factoryDisabled,
  statusOptions,
  getStatusClass,
  fetchOrders,
  resetFilter,
} = useOrderList()

const {
  stagedItems,
  removeStagedItem,
  submitting,
  submitAll,
  editStagedVisible,
  editStagedData,
  editAvailableStock,
  openEditStaged,
  saveEditStaged,
  excelFile,
  importing,
  isDragOver,
  handleExcelSelect,
  onDrop,
  downloadTemplate,
  handleImport,
  detailOpen,
  detailData,
  editForm,
  availableStockin,
  openDetail,
  saveEditOrder,
  saving,
  deductRetryPending,
  retryDeductUpdate,
  confirmDialog,
  genUid,
  handleDeleteOrder,
} = useOrderActions(form, isOrder, fetchOrders)

const authStore = useAuthStore()
const canDelete = computed(() => authStore.hasPermission('order_manage'))

/**
 * 粘贴图片识别确认后的条目并入暂存区。
 *
 * 它们是纯前端条目（origin: 'ocr'），与手工新增同理：不受 Excel 导入
 * 「用服务端结果替换 import 条目」的影响，提交走同一条批量提交流程。
 */
function addStagedItems(items: StagedItem[]) {
  stagedItems.value.push(...items)
}

function addStaged() {
  // 主操作始终可点：缺项时把「缺什么」说出来，而不是把按钮变灰后沉默。
  // （原先按钮被 :disabled 拦掉，这段提示在鼠标与键盘两条路径上都不可能出现）
  if (missingFields.value.length) {
    showToast(`请先填写：${missingFields.value.join('、')}`, 'warning')
    return
  }
  // 提交前最终校验：字段实时标红可能被绕过（回车 / 直接点按钮），越界一律不进暂存区
  if (quantityOutOfRange.value) {
    showToast(QUANTITY_RANGE_MESSAGE, 'warning')
    return
  }
  stagedItems.value.push({
    uid: genUid(),
    // 手工条目只存在于前端：导入时不会被服务端结果替换
    origin: 'manual',
    type: form.type,
    customer: form.customer,
    productId: form.productId,
    productName: form.productSearch,
    quantity: form.quantity,
    date: form.date,
    note: form.note,
    deductStock: isOrder.value ? form.deductStock : false,
    deductQuantity: isOrder.value && form.deductStock ? form.deductQuantity : 0,
  })
  resetFormAfterAdd()
  inputPanelRef.value?.resetQuantityValidation()
  // 连续录入：焦点交回产品输入框，用户不必从页首重新 Tab 16 个框架层停点
  void nextTick(() => {
    inputPanelRef.value?.focusProductInput()
    showToast(`已添加 1 条，暂存区共 ${stagedItems.value.length} 条`, 'success')
  })
}

/** 记录类型切换：重置分页并重新查询 */
function handleChangeRecordType(value: 'order' | 'stockin') {
  recordType.value = value
  currentPage.value = 1
  fetchOrders()
}

/** 分页变化：仅更新页码（子组件已触发 fetchOrders） */
function handleChangePage(page: number) {
  currentPage.value = page
}

// ===== Tab switching =====
const activeTab = ref<'input' | 'records'>('input')

// 切换到记录查询tab时自动加载数据
watch(activeTab, (tab) => {
  // 每次进入都重新拉取：暂存区提交可能新增了订单，若沿用旧列表会显示过期数据
  if (tab === 'records') fetchOrders()
})
</script>

<style scoped>
/* ===== 页面容器 ===== */
.co-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* ===== 卡片头部 ===== */

.co-tab-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* ===== 双栏主体 ===== */
.page-card-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
@media (max-width: 1024px) {
  .page-card-body {
    grid-template-columns: 1fr;
  }
}

/* 栏间分隔线 */
.co-tab-content :deep(.co-col + .co-col) {
  border-left: 1px solid var(--color-border, #cbd5e1);
}

/* ===== Tab 切换栏 ===== */
.co-tab-bar {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.co-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  min-height: 32px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}
/* hover 只改颜色，不做位移：列表/切换器上的位移会造成扫读抖动与每帧重排 */
.co-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-tab-btn:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}
.co-tab-btn.active {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  box-shadow: inset 0 0 0 1px var(--color-primary-200, var(--color-primary-100));
}
</style>

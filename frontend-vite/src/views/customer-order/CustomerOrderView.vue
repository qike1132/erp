<template>
  <div class="co-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="co-tab-bar">
          <button :class="['co-tab-btn', activeTab === 'input' && 'active']" @click="activeTab = 'input'">
            录入
          </button>
          <button :class="['co-tab-btn', activeTab === 'records' && 'active']" @click="activeTab = 'records'">
            记录查询
          </button>
        </div>
      </div>

      <!-- TAB: 录入 -->
      <div v-show="activeTab === 'input'" class="co-tab-content">
        <div class="page-card-body">
          <!-- 左栏：录入表单 -->
          <OrderInputPanel
            v-model:is-drag-over="isDragOver"
            :form="form"
            :is-order="isOrder"
            :is-custom-order="isCustomOrder"
            :order-type-options="orderTypeOptions"
            :customer-options="customerOptions"
            :country-options="countryStore.countryOptions"
            :can-add="canAdd"
            :available-stock="availableStock"
            :deduct-info-visible="deductInfoVisible"
            :excel-file="excelFile"
            :importing="importing"
            :search-products="searchProducts"
            :select-product="selectProduct"
            :handle-deduct-preview="handleDeductPreview"
            :open-deduct-edit="openDeductEdit"
            :open-country-dialog="openCountryDialog"
            :handle-excel-select="handleExcelSelect"
            :on-drop="onDrop"
            :download-template="downloadTemplate"
            :handle-import="handleImport"
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
          :record-type="recordType"
          :record-type-options="recordTypeOptions"
          :customer-options="customerOptions"
          :filter-order-type-options="filterOrderTypeOptions"
          :factory-options="factoryOptions"
          :factory-disabled="factoryDisabled"
          :status-options="statusOptions"
          :order-records="orderRecords"
          :is-loading-records="isLoadingRecords"
          :is-fetching-records="isFetchingRecords"
          :current-page="currentPage"
          :total-pages="totalPages"
          v-model:per-page="perPage"
          v-model:show-filter="showFilter"
          v-model:filter-customer="filterCustomer"
          v-model:filter-order-type="filterOrderType"
          v-model:filter-status="filterStatus"
          v-model:filter-factory="filterFactory"
          v-model:filter-start="filterStart"
          v-model:filter-end="filterEnd"
          :fetch-orders="fetchOrders"
          :reset-filter="resetFilter"
          @change-record-type="handleChangeRecordType"
          @view-detail="openDetail"
          @change-page="handleChangePage"
        />
      </div>

    </div>

    <!-- 订单详情弹窗 -->
    <EditOrderModal
      v-model:open="detailOpen"
      :detail-data="detailData"
      :edit-form="editForm"
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
      :edit-staged-data="editStagedData"
      :edit-available-stock="editAvailableStock"
      :customer-options="customerOptions"
      :save-edit-staged="saveEditStaged"
    />

    <!-- 添加国家弹窗 -->
    <CountryDialog
      v-model:open="countryDialogVisible"
      v-model:new-country-name="newCountryName"
      :save-country="saveCountry"
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
import { ref, watch } from 'vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { showToast } from '@/composables/useToast'
import { useOrderForm } from './composables/useOrderForm'
import { useOrderList } from './composables/useOrderList'
import { useOrderActions } from './composables/useOrderActions'

import OrderInputPanel from './components/OrderInputPanel.vue'
import StagingArea from './components/StagingArea.vue'
import OrderRecordQuery from './components/OrderRecordQuery.vue'
import EditOrderModal from './components/EditOrderModal.vue'
import EditStagedModal from './components/EditStagedModal.vue'
import CountryDialog from './components/CountryDialog.vue'

const {
  form,
  isOrder,
  isCustomOrder,
  orderTypeOptions,
  canAdd,
  customerOptions,
  countryStore,
  searchProducts,
  selectProduct,
  countryDialogVisible,
  newCountryName,
  openCountryDialog,
  saveCountry,
  availableStock,
  deductInfoVisible,
  handleDeductPreview,
  openDeductEdit,
  resetFormAfterAdd,
} = useOrderForm()

const {
  showFilter,
  filterCustomer,
  filterOrderType,
  filterStatus,
  filterFactory,
  filterStart,
  filterEnd,
  currentPage,
  perPage,
  totalPages,
  isLoadingRecords,
  isFetchingRecords,
  orderRecords,
  recordType,
  recordTypeOptions,
  filterOrderTypeOptions,
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
} = useOrderActions(form, isOrder, fetchOrders)

function addStaged() {
  if (!canAdd.value) {
    if (!form.productId && form.productSearch) {
      showToast('请从下拉列表中选择产品', 'warning')
    } else {
      showToast('请填写日期、客户和产品', 'warning')
    }
    return
  }
  stagedItems.value.push({
    uid: genUid(),
    type: form.type,
    orderType: form.orderType,
    customer: form.customer,
    productId: form.productId,
    productName: form.productSearch,
    quantity: form.quantity,
    date: form.date,
    note: form.note,
    country: isCustomOrder.value ? form.country : '',
    deductStock: isOrder.value ? form.deductStock : false,
    deductQuantity: isOrder.value && form.deductStock ? form.deductQuantity : 0,
  })
  resetFormAfterAdd()
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
  if (tab === 'records' && orderRecords.value.length === 0) {
    fetchOrders()
  }
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
  border-left: 2px solid var(--color-border, #cbd5e1);
}

/* ===== Tab 切换栏 ===== */
.co-tab-bar {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.co-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}
.co-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.co-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
</style>

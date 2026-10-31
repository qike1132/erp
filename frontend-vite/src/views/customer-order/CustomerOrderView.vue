<template>
  <div class="co-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部（2026-10-13）：左上角原「录入」是 2026-10-06 记录查询 tab 收敛至 /report
           后留下的单 tab（点了没反应），已删除；订单/备货切换器自左栏列标题上移到页头左上角，
           让「这一页在录什么」第一眼可见。 -->
      <div class="page-card-header">
        <OrderTypeSwitch v-model:form="form" :is-order="isOrder" />
      </div>

      <!-- 录入主区 -->
      <div class="co-tab-content">
        <div class="page-card-body">
          <!-- 左栏：录入表单 -->
          <OrderInputPanel
            ref="inputPanelRef"
            v-model:is-drag-over="isDragOver"
            v-model:form="form"
            :is-order="isOrder"
            :customer-options="customerOptions"
            :customer-options-error="customerOptionsError"
            :missing-fields="missingFields"
            :available-stock="availableStock"
            :stock-error="stockError"
            :deduct-info-visible="deductInfoVisible"
            :excel-file="excelFile"
            :importing="importing"
            :search-products="searchProducts"
            :product-search-failed="productSearchFailed"
            :fetch-sku-list="fetchSkuList"
            :sku-list-error="skuListError"
            :select-product="selectProduct"
            :handle-deduct-preview="handleDeductPreview"
            :open-deduct-edit="openDeductEdit"
            :handle-excel-select="handleExcelSelect"
            :on-drop="onDrop"
            :download-template="downloadTemplate"
            :handle-import="handleImport"
            :add-staged-items="addStagedItems"
            @add-staged="addStaged"
            @retry-customers="retryCustomers"
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

    </div>

    <!-- 编辑暂存弹窗 -->
    <EditStagedModal
      v-model:open="editStagedVisible"
      v-model:edit-staged-data="editStagedData"
      :edit-available-stock="editAvailableStock"
      :edit-stock-state="editStockState"
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
import { ref, nextTick } from 'vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { showToast } from '@/composables/useToast'
import { QUANTITY_RANGE_MESSAGE } from './composables/quantityRange'
import { useOrderForm } from './composables/useOrderForm'
import { useOrderActions } from './composables/useOrderActions'
import type { StagedItem } from './composables/types'

import OrderInputPanel from './components/OrderInputPanel.vue'
import OrderTypeSwitch from './components/OrderTypeSwitch.vue'
import StagingArea from './components/StagingArea.vue'
import EditStagedModal from './components/EditStagedModal.vue'

const {
  form,
  isOrder,
  missingFields,
  quantityOutOfRange,
  planSplitsInvalid,
  customerOptions,
  customerOptionsError,
  retryCustomers,
  searchProducts,
  productSearchFailed,
  fetchSkuList,
  skuListError,
  selectProduct,
  availableStock,
  deductInfoVisible,
  stockError,
  fetchAvailableStock,
  handleDeductPreview,
  openDeductEdit,
  resetFormAfterAdd,
} = useOrderForm()

/** 录入面板引用：新增成功后把焦点交回产品输入框 */
const inputPanelRef = ref<InstanceType<typeof OrderInputPanel> | null>(null)

const {
  stagedItems,
  removeStagedItem,
  submitting,
  submitAll,
  editStagedVisible,
  editStagedData,
  editAvailableStock,
  editStockState,
  openEditStaged,
  saveEditStaged,
  excelFile,
  importing,
  isDragOver,
  handleExcelSelect,
  onDrop,
  downloadTemplate,
  handleImport,
  confirmDialog,
  genUid,
} = useOrderActions(form, isOrder)

/**
 * 粘贴图片识别确认后的条目并入暂存区。
 *
 * 它们是纯前端条目（origin: 'ocr'），与手工新增同理：不受 Excel 导入
 * 「用服务端结果替换 import 条目」的影响，提交走同一条批量提交流程。
 */
function addStagedItems(items: StagedItem[]) {
  stagedItems.value.push(...items)
}

async function addStaged() {
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
  // 分批出货计划值错误（排满口径/行完整性）与数量越界同通道拦截
  if (planSplitsInvalid.value) {
    showToast(planSplitsInvalid.value, 'warning')
    return
  }
  // 抵扣量提交前复核（A-M36）：界面上的「可用备货」是上次查询的快照，期间可能有
  // 别的单据扣过同一批备货；后端对超量抵扣做 min() 静默截断（不报错），用户只会
  // 在事后发现「说好扣 10 实际只扣了 6」。这里重新查一次，超量就拦住并给出具体数字。
  if (isOrder.value && form.deductStock && form.deductQuantity > 0) {
    await fetchAvailableStock()
    if (stockError.value) {
      showToast(`可用备货未能确认：${stockError.value}`, 'warning')
      return
    }
    if (form.deductQuantity > availableStock.value) {
      showToast(`抵扣数量 ${form.deductQuantity} 超过当前可用备货 ${availableStock.value}，请调整后再添加`, 'warning')
      return
    }
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
    // 分批出货计划仅订单类型生效；备货条目一律无计划
    shipmentPlans: isOrder.value ? form.shipmentPlans.map((s) => ({ ...s })) : [],
  })
  resetFormAfterAdd()
  inputPanelRef.value?.resetQuantityValidation()
  // 连续录入：焦点交回产品输入框，用户不必从页首重新 Tab 16 个框架层停点
  void nextTick(() => {
    inputPanelRef.value?.focusProductInput()
    showToast(`已添加 1 条，暂存区共 ${stagedItems.value.length} 条`, 'success')
  })
}
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
</style>

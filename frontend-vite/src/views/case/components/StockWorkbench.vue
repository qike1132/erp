<template>
  <div class="sw-wrap">
    <!-- 录入 + 暂存 + 导入 -->
    <div class="sw-top">
      <StockEntryCard
        v-model:form="form"
        :mode="mode"
        :staged-count="staged.length"
        :customer-options="customerOptions"
        :can-add="canAdd"
        :quantity-warning="quantityWarning"
        :available-stock="availableStock"
        :staged-qty-selected="stagedQtySelected"
        :search-fn="searchCaseProducts"
        @select="onProductSelect"
        @add="addStaged"
      />
      <div class="sw-side">
        <StagedCart
          :mode="mode"
          :staged="staged"
          :staged-total="stagedTotal"
          :submitting="submitting"
          :last-failures="lastFailures"
          @remove="removeStaged"
          @quantity-change="updateStagedQuantity"
          @clear="clearStaged"
          @submit="submitBatch"
        />
        <BatchImportCard
          v-model:open="showBatchUpload"
          :mode="mode"
          :excel-file="excelFile"
          :importing="importing"
          :template-downloading="templateDownloading"
          @excel-change="onExcelFileChange"
          @download-template="downloadTemplate"
          @import="importExcel"
        />
      </div>
    </div>

    <!-- 记录列表 -->
    <StockRecordsPanel
      :kind="mode"
      :customer-options="customerOptions"
      :action-id="deletingId"
      @edit="openEdit"
      @delete="handleDelete"
    />

    <!-- 编辑弹窗 -->
    <EditRecordDialog
      v-model:open="editDialogOpen"
      v-model:form="editForm"
      :mode="mode"
      :customer-options="customerOptions"
      :saving="saving"
      @save="saveEdit"
    />

    <!-- 确认弹窗（暂存移除 / 记录删除共用） -->
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
 * StockWorkbench — 皮套入库/出库工作台（每个模式独立实例）。
 * 组合：useCaseOptions（客户/产品搜索）+ useCaseStockWorkbench（录入/暂存/提交/导入）
 *      + useCaseRecordActions（记录编辑/删除）。
 */
import StockEntryCard from './StockEntryCard.vue'
import StagedCart from './StagedCart.vue'
import BatchImportCard from './BatchImportCard.vue'
import StockRecordsPanel from './StockRecordsPanel.vue'
import EditRecordDialog from './EditRecordDialog.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { computed, toRef } from 'vue'
import { useCaseOptions } from '../composables/useCaseOptions'
import { useCaseStockWorkbench } from '../composables/useCaseStockWorkbench'
import { useCaseRecordActions } from '../composables/useCaseRecordActions'
import type { CaseStockRecord } from '@/api/case'

const props = defineProps<{
  /** 工作台模式：入库 / 出库（实例级固定） */
  mode: 'stockin' | 'stockout'
}>()

const { customerOptions, searchCaseProducts } = useCaseOptions()

const {
  form,
  availableStock,
  quantityWarning,
  canAdd,
  onProductSelect,
  staged,
  stagedTotal,
  addStaged,
  removeStaged,
  updateStagedQuantity,
  clearStaged,
  submitting,
  submitBatch,
  lastFailures,
  showBatchUpload,
  excelFile,
  importing,
  templateDownloading,
  onExcelFileChange,
  downloadTemplate,
  importExcel,
  confirmDialog,
} = useCaseStockWorkbench(props.mode)

/** 当前选中产品在本单已暂存数量（录入卡提示用） */
const stagedQtySelected = computed(() =>
  staged.value
    .filter((s) => s.productId === form.productId)
    .reduce((sum, s) => sum + s.quantity, 0),
)

const recordActions = useCaseRecordActions(toRef(props, 'mode'), confirmDialog)
const {
  editDialogOpen,
  editForm,
  saving,
  saveEdit,
  deletingId,
} = recordActions

function openEdit(row: CaseStockRecord) {
  void recordActions.openEdit(row)
}
function handleDelete(row: CaseStockRecord) {
  void recordActions.handleDelete(row)
}
</script>

<style scoped>
.sw-wrap {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.sw-top {
  display: grid;
  grid-template-columns: 1.1fr 1fr;
  gap: 16px;
  align-items: start;
}
.sw-side {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
@media (max-width: 992px) {
  .sw-top { grid-template-columns: 1fr; }
}
</style>

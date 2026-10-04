<template>
  <div class="sw-wrap">
    <!-- 录入 + 暂存 + 导入 -->
    <div class="sw-top">
      <StockEntryCard
        v-model:form="form"
        :staged-count="staged.length"
        :submitting="submitting"
        @add="addStagedBatch"
        @submit="submitDirect"
      />
      <div class="sw-side">
        <StagedCart
          :staged="staged"
          :staged-total="stagedTotal"
          :submitting="submitting"
          :last-failures="lastFailures"
          @remove="removeStaged"
          @quantity-change="updateStagedQuantity"
          @direction-change="updateStagedDirection"
          @date-change="updateStagedDate"
          @note-change="updateStagedNote"
          @clear="clearStaged"
          @submit="submitBatch"
        />
        <BatchImportCard
          v-model:open="showBatchUpload"
          :direction="form.direction"
          :excel-file="excelFile"
          :importing="importing"
          :template-downloading="templateDownloading"
          @excel-change="onExcelFileChange"
          @download-template="downloadTemplate"
          @import="importExcel"
        />
      </div>
    </div>

    <!-- 记录列表（入库出库混排） -->
    <StockRecordsPanel
      :action-id="deletingId"
      @edit="openEdit"
      @delete="handleDelete"
      @export="exportRecords"
    />

    <!-- 编辑弹窗 -->
    <EditRecordDialog
      v-model:open="editDialogOpen"
      v-model:form="editForm"
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
 * StockWorkbench — 皮套出入库工作台（入库/出库合一）。
 * 录入：一行快捷条（方向/产品/数量）→ Enter 直接提交单条；多条走「暂存」批量提交。
 */
import StockEntryCard from './StockEntryCard.vue'
import StagedCart from './StagedCart.vue'
import BatchImportCard from './BatchImportCard.vue'
import StockRecordsPanel from './StockRecordsPanel.vue'
import EditRecordDialog from './EditRecordDialog.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { caseApi } from '@/api'
import { useCaseStockWorkbench } from '../composables/useCaseStockWorkbench'
import { useCaseRecordActions } from '../composables/useCaseRecordActions'
import type { CaseMovement } from '@/api/case'

const {
  form,
  staged,
  stagedTotal,
  addStagedBatch,
  removeStaged,
  updateStagedQuantity,
  updateStagedDirection,
  updateStagedDate,
  updateStagedNote,
  clearStaged,
  submitting,
  submitBatch,
  submitDirect,
  lastFailures,
  showBatchUpload,
  excelFile,
  importing,
  templateDownloading,
  onExcelFileChange,
  downloadTemplate,
  importExcel,
  confirmDialog,
} = useCaseStockWorkbench()

const recordActions = useCaseRecordActions(confirmDialog)
const { editDialogOpen, editForm, saving, saveEdit, deletingId } = recordActions

function openEdit(row: CaseMovement) {
  void recordActions.openEdit(row)
}
function handleDelete(row: CaseMovement) {
  void recordActions.handleDelete(row)
}
// 第十四轮：导出随当前筛选（面板 emit 携带）—— 此前硬编码 scope 导出全量，与所见不符。
function exportRecords(f: { direction: '' | 'in' | 'out'; start: string; end: string }) {
  void caseApi.exportXlsx({
    scope: 'movements',
    direction: f.direction || undefined,
    start_date: f.start || undefined,
    end_date: f.end || undefined,
  })
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

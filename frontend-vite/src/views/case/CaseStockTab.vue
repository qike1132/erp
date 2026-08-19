<template>
  <div class="cs-stock">
    <!-- 模式切换 -->
    <div class="cs-mode-toggle" role="tablist">
      <button role="tab" :aria-selected="mode === 'stockin'" :class="['cs-mode-btn', { active: mode === 'stockin' }]" @click="switchMode('stockin')" aria-label="入库">
        <FontAwesomeIcon icon="truck-loading" />入库
      </button>
      <button role="tab" :aria-selected="mode === 'stockout'" :class="['cs-mode-btn', { active: mode === 'stockout', 'out-mode': mode === 'stockout' }]" @click="switchMode('stockout')" aria-label="出库">
        <FontAwesomeIcon icon="shipping-fast" />出库
      </button>
    </div>

    <!-- 上半部分：录入表单 + 暂存列表 -->
    <CaseStockEntryPanel
      v-model:show-batch-upload="showBatchUpload"
      :mode="mode"
      v-model:form="form"
      :staged="staged"
      :current-stock="currentStock"
      :customer-options="customerOptions"
      :can-add="canAdd"
      :search-fn="searchCaseProducts"
      :excel-file="excelFile"
      :importing="importing"
      :template-downloading="templateDownloading"
      @product-select="onProductSelect"
      @add-staged="addStaged"
      @remove-staged="removeStagedItem"
      @excel-change="onExcelFileChange"
      @download-template="handleDownloadTemplate"
      @import-excel="handleImportExcel"
    />

    <!-- 提交按钮 -->
    <div class="cs-submit-bar">
      <button
        :class="['cs-submit-large', mode === 'stockin' ? 'cs-submit-primary' : 'cs-submit-danger']"
        :disabled="!staged.length"
        @click="submitBatch"
      >
        <FontAwesomeIcon icon="paper-plane" style="margin-right: 8px" />
        {{ submitting ? '提交中…' : mode === 'stockin' ? '提交入库' : '提交出库' }}
      </button>
    </div>

    <!-- 入库记录列表 -->
    <CaseStockRecordSection
      v-model:show-filter="siShowFilter"
      v-model:f-customer="siFCustomer"
      v-model:f-start="siFStart"
      v-model:f-end="siFEnd"
      kind="stockin"
      :list="siList"
      :columns="siColumns"
      :is-loading="siIsLoading"
      :is-fetching="siIsFetching"
      :per-page="siPerPage"
      :total-pages="siTotalPages"
      :customer-options="customerOptions"
      :action-id="actionId"
      @search="siSearch"
      @page="onSiPageChange"
      @edit="openEditModal('stockin', $event)"
      @delete="handleDelete('stockin', $event)"
    />

    <!-- 出库记录列表 -->
    <CaseStockRecordSection
      v-model:show-filter="soShowFilter"
      v-model:f-customer="soFCustomer"
      v-model:f-start="soFStart"
      v-model:f-end="soFEnd"
      kind="stockout"
      :list="soList"
      :columns="soColumns"
      :is-loading="soIsLoading"
      :is-fetching="soIsFetching"
      :per-page="soPerPage"
      :total-pages="soTotalPages"
      :customer-options="customerOptions"
      :action-id="actionId"
      @search="soSearch"
      @page="onSoPageChange"
      @edit="openEditModal('stockout', $event)"
      @delete="handleDelete('stockout', $event)"
    />

    <!-- 编辑弹窗 -->
    <UiDialog v-model:open="editDialogOpen" :title="editMode === 'stockin' ? '编辑入库记录' : '编辑出库记录'" max-width-class="max-w-[500px]">
      <div class="cs-edit-form">
        <div class="cs-form-field">
          <label class="cs-form-label">客户名称</label>
          <UiSelect v-model="editForm.customer" :options="editMode === 'stockout' ? [{ value: '', label: '无' }, ...customerOptions] : customerOptions" />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">{{ editMode === 'stockin' ? '入库日期' : '出库日期' }}</label>
          <UiDatePicker v-model="editForm.date" style="width: 100%" />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">产品名称</label>
          <input class="cs-input" :value="editForm.productName" disabled aria-label="产品名称" />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">{{ editMode === 'stockin' ? '入库数量' : '出库数量' }}</label>
          <input type="number" class="cs-input" v-model.number="editForm.quantity" min="1" step="1" :aria-label="editMode === 'stockin' ? '入库数量' : '出库数量'" />
        </div>
        <div class="cs-form-field">
          <label class="cs-form-label">备注</label>
          <textarea v-model="editForm.note" class="cs-textarea" rows="2" aria-label="备注" />
        </div>
      </div>
      <template #footer>
        <button class="cs-action-btn cs-action-outline" @click="editDialogOpen = false" aria-label="取消">取消</button>
        <button class="cs-action-btn cs-action-primary" @click="saveEdit" aria-label="保存">保存</button>
      </template>
    </UiDialog>

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
 * CaseStockTab — 皮套入库/出库主容器
 * 拆分后职责：模式切换 + 组合编排各区块子组件与 composables。
 *  - 录入表单/暂存列表 → CaseStockEntryPanel + useCaseStockEntry
 *  - 记录列表（筛选/分页/查询）→ CaseStockRecordSection + useCaseStockRecords
 *  - 批量提交/导入/删除/编辑 → useCaseStockActions（既有）
 */
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import CaseStockEntryPanel from './components/CaseStockEntryPanel.vue'
import CaseStockRecordSection from './components/CaseStockRecordSection.vue'
import { useCaseStockActions } from './composables/useCaseStockActions'
import { useCaseStockEntry } from './composables/useCaseStockEntry'
import { useCaseStockRecords } from './composables/useCaseStockRecords'

// === 录入区状态（模式/客户/产品搜索/表单/暂存列表）===
const {
  mode,
  switchEntryMode,
  customerOptions,
  searchCaseProducts,
  currentStock,
  onProductSelect,
  form,
  canAdd,
  staged,
  addStaged,
} = useCaseStockEntry()

// === 动作（批量提交/导入/删除/编辑/确认弹窗）===
const {
  confirmDialog,
  submitting,
  submitBatch,
  showBatchUpload,
  excelFile,
  importing,
  templateDownloading,
  onExcelFileChange,
  handleDownloadTemplate,
  handleImportExcel,
  actionId,
  handleDelete,
  editDialogOpen,
  editMode,
  editForm,
  openEditModal,
  saveEdit,
} = useCaseStockActions(mode, staged, currentStock)

/** 切换入库/出库模式：重置录入区并清空已选 Excel 文件（原内联逻辑） */
function switchMode(nextMode: 'stockin' | 'stockout') {
  switchEntryMode(nextMode)
  excelFile.value = null
}

async function removeStagedItem(idx: number) {
  const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
  if (!ok) return
  staged.value.splice(idx, 1)
}

// === 入库记录列表 ===
const {
  showFilter: siShowFilter,
  fCustomer: siFCustomer,
  fStart: siFStart,
  fEnd: siFEnd,
  totalPages: siTotalPages,
  perPage: siPerPage,
  isLoading: siIsLoading,
  isFetching: siIsFetching,
  list: siList,
  columns: siColumns,
  onPageChange: onSiPageChange,
  search: siSearch,
} = useCaseStockRecords('stockin')

// === 出库记录列表 ===
const {
  showFilter: soShowFilter,
  fCustomer: soFCustomer,
  fStart: soFStart,
  fEnd: soFEnd,
  totalPages: soTotalPages,
  perPage: soPerPage,
  isLoading: soIsLoading,
  isFetching: soIsFetching,
  list: soList,
  columns: soColumns,
  onPageChange: onSoPageChange,
  search: soSearch,
} = useCaseStockRecords('stockout')
</script>

<style scoped>
.cs-stock {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Mode toggle */
.cs-mode-toggle {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  align-self: flex-start;
}
.cs-mode-btn {
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  border-radius: 9px;
  background: transparent;
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}
.cs-mode-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.cs-mode-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
.cs-mode-btn.active.out-mode {
  background: linear-gradient(135deg, var(--color-danger-50), var(--color-danger-100));
  color: var(--color-danger-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(234, 84, 85, 0.2);
}

/* Form fields（编辑弹窗） */
.cs-form-field {
  margin-bottom: 12px;
}
.cs-form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.cs-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}
.cs-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cs-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cs-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  resize: vertical;
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}
.cs-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cs-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* Submit buttons */
.cs-submit-bar {
  text-align: center;
  padding: 8px 0;
}
.cs-submit-large {
  min-width: 200px;
  padding: 12px 24px;
  border: none;
  border-radius: 9px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: box-shadow 0.3s ease, transform 0.3s ease;
  color: white;
}
.cs-submit-large.cs-submit-primary { background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); }
.cs-submit-large.cs-submit-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3); }
.cs-submit-large.cs-submit-danger { background: linear-gradient(135deg, var(--color-danger-500), var(--color-danger-700)); }
.cs-submit-large.cs-submit-danger:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(234, 84, 85, 0.3); }
.cs-submit-large:disabled { opacity: 0.4; cursor: not-allowed; }

/* Action buttons（编辑弹窗底部按钮） */
.cs-action-btn {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
  color: var(--color-text-secondary);
}
.cs-action-primary { color: var(--color-primary-600); }
.cs-action-primary:hover:not(:disabled) { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.cs-action-outline { }
.cs-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Edit form */
.cs-edit-form {
  display: flex;
  flex-direction: column;
  gap: 0;
}
</style>

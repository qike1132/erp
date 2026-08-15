<template>
  <div class="co-col">
    <div class="co-col-title">
      <span><FontAwesomeIcon icon="edit" aria-hidden="true" /> {{ isOrder ? '订单信息录入' : '备货信息录入' }}</span>
      <div class="co-type-switch">
        <button :class="['co-type-btn', isOrder && 'active']" @click="form.type = 'order'">
          <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" />订单
        </button>
        <button :class="['co-type-btn', !isOrder && 'active']" @click="form.type = 'stockin'">
          <FontAwesomeIcon icon="truck-loading" aria-hidden="true" />备货
        </button>
      </div>
    </div>
    <div class="co-col-scroll">
      <form @submit.prevent="emit('add-staged')">
        <div class="co-form-row">
          <div class="co-form-group">
            <label class="co-label">订单类型 <span class="co-required">*</span></label>
            <UiSelect
              v-model="form.orderType"
              placeholder="请选择订单类型"
              style="width: 100%"
              :options="orderTypeOptions"
            />
          </div>
          <div v-if="isCustomOrder" class="co-form-group">
            <label class="co-label">国家</label>
            <div style="display: flex; gap: 8px; align-items: center;">
              <UiSelect
                v-model="form.country"
                placeholder="请选择国家"
                style="flex: 1"
                :options="countryOptions"
              />
              <UiButton variant="outline" style="white-space: nowrap; flex-shrink: 0;" @click="openCountryDialog">
                <FontAwesomeIcon icon="plus" aria-hidden="true" />
              </UiButton>
            </div>
          </div>
        </div>
        <div class="co-form-row">
          <div v-if="isOrder" class="co-form-group">
            <label class="co-label">订单时间 <span class="co-required">*</span></label>
            <UiDatePicker v-model="form.date" style="width: 100%" />
          </div>
          <div v-else class="co-form-group">
            <label class="co-label">备货时间 <span class="co-required">*</span></label>
            <UiDatePicker v-model="form.date" style="width: 100%" />
          </div>
          <div class="co-form-group">
            <label class="co-label">客户名称 <span class="co-required">*</span></label>
            <UiSelect
              v-model="form.customer"
              placeholder="请选择客户"
              style="width: 100%"
              :options="customerOptions"
            />
          </div>
        </div>

        <div class="co-form-group">
          <label class="co-label">产品名称 <span class="co-required">*</span></label>
          <UiAutocomplete
            v-model="form.productSearch"
            :searchFn="searchProducts"
            placeholder="输入产品名称搜索"
            @select="selectProduct"
            @update:modelValue="form.productId = 0"
          >
            <template #option="{ item }">
              {{ item.name }}
            </template>
          </UiAutocomplete>
        </div>

        <div class="co-form-row">
          <div class="co-form-group">
            <label class="co-label"
              >{{ isOrder ? '订单数量' : '备货数量' }} <span class="co-required">*</span></label
            >
            <input type="number" class="form-number-input" v-model.number="form.quantity" min="1" max="9999999" step="1" style="width: 100%" name="quantity" autocomplete="off" />
          </div>
          <div v-if="isOrder" class="co-form-group">
            <label class="co-label">抵扣备货数量</label>
            <div class="co-deduct-row">
              <button
                type="button"
                :class="['co-btn-deduct', form.deductStock && 'active']"
                @click="handleDeductPreview"
              >
                <FontAwesomeIcon icon="boxes" aria-hidden="true" />抵扣备货
              </button>
              <button
                type="button"
                class="co-deduct-display"
                :style="{ borderColor: form.deductQuantity > 0 ? 'var(--color-ocean-deep)' : 'var(--color-text-muted)' }"
                @click="openDeductEdit"
              >
                <FontAwesomeIcon icon="edit" style="font-size: 11px"  aria-hidden="true" />抵扣: <strong>{{ form.deductQuantity }}</strong>
              </button>
            </div>
            <div v-if="deductInfoVisible" class="co-deduct-info">
              <small v-if="availableStock > 0" style="color: var(--color-success-700)">
                <FontAwesomeIcon icon="check-circle" aria-hidden="true" /> 可用备货: <strong>{{ availableStock }}</strong> 件
                <span v-if="form.deductQuantity > 0" style="margin-left: 8px; color: var(--color-ocean-text)">
                  <FontAwesomeIcon icon="arrow-right" aria-hidden="true" /> 抵扣后剩余:
                  <strong>{{ availableStock - form.deductQuantity }}</strong> 件
                </span>
              </small>
              <small v-else style="color: var(--color-warning-500)"><FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> 暂无可用备货</small>
            </div>
          </div>
        </div>

        <div class="co-form-group">
          <label class="co-label">备注</label>
          <textarea
            v-model="form.note"
            rows="2"
            class="co-textarea"
            :placeholder="isOrder ? '例如：加急订单' : '例如：批量备货'"
          />
        </div>

        <!-- 批量导入 -->
        <div class="co-section-label"><FontAwesomeIcon icon="file-import" aria-hidden="true" /> 批量导入</div>
        <div
          class="co-section-header co-droppable"
          :class="{ 'co-drag-over': isDragOver }"
          @click="excelInputRef?.click()"
          @dragover.prevent="emit('update:isDragOver', true)"
          @dragleave="emit('update:isDragOver', false)"
          @drop.prevent="onDrop"
        >
          <label class="form-label co-droppable-label">
            <FontAwesomeIcon icon="file-excel" class="label-icon" aria-hidden="true" />
            <span v-if="excelFile" class="co-file-inline co-file-inline-success"><FontAwesomeIcon icon="file-excel" aria-hidden="true" />{{ excelFile.name }}</span>
            <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
          </label>
          <div class="co-inline-actions">
            <button class="co-inline-btn" @click.stop="downloadTemplate">模板</button>
            <button class="co-inline-btn co-inline-btn-success" :disabled="!excelFile" @click.stop="handleImport">
              {{ importing ? '导入中…' : '导入' }}
            </button>
          </div>
          <input
            ref="excelInputRef"
            type="file"
            accept=".xlsx,.xls"
            style="display: none"
            @change="handleExcelSelect"
          />
        </div>

        <UiButton variant="primary" :disabled="!canAdd" style="margin-top: 15px" @click="emit('add-staged')">
          <FontAwesomeIcon icon="plus-circle" aria-hidden="true" />{{ isOrder ? '新增订单' : '新增备货' }}
        </UiButton>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiAutocomplete from '@/components/ui/UiAutocomplete.vue'
import type { FormState } from '../composables/types'

defineProps<{
  form: FormState
  isOrder: boolean
  isCustomOrder: boolean
  orderTypeOptions: { label: string; value: string }[]
  customerOptions: { label: string; value: string }[]
  countryOptions: { label: string; value: string }[]
  canAdd: boolean
  availableStock: number
  deductInfoVisible: boolean
  excelFile: File | null
  importing: boolean
  isDragOver: boolean
  searchProducts: (q: string) => Promise<any[]>
  selectProduct: (item: any) => void
  handleDeductPreview: () => void
  openDeductEdit: () => void
  openCountryDialog: () => void
  handleExcelSelect: (e: Event) => void
  onDrop: (e: DragEvent) => void
  downloadTemplate: () => void
  handleImport: () => void
}>()

const emit = defineEmits<{
  'add-staged': []
  'update:isDragOver': [value: boolean]
}>()

const excelInputRef = ref<HTMLInputElement | null>(null)
</script>

<style scoped>
/* ===== 表单输入 ===== */
.form-number-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  -moz-appearance: textfield;
}
.form-number-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.form-number-input::-webkit-inner-spin-button,
.form-number-input::-webkit-outer-spin-button {
  opacity: 1;
}
.form-number-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}

/* ===== 栏目 ===== */
.co-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.co-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.co-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}

.co-col-scroll {
  padding: 16px 20px;
  overflow-y: auto;
  flex: 1;
}

/* ===== 区块标题 ===== */
.co-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  min-height: 40px;
  box-sizing: border-box;
  cursor: default;
  transition: border-color 0.3s ease, background 0.3s ease;
}
.co-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: var(--color-slate-50);
}
.co-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
}

/* ===== Droppable ===== */
.co-droppable {
  cursor: pointer;
}
.co-droppable.co-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.co-droppable-label {
  display: flex !important;
  margin-bottom: 0;
  cursor: pointer;
  font-size: 14px !important;
  font-weight: 400 !important;
  color: var(--color-text-muted) !important;
}
.co-droppable-label .label-icon {
  color: var(--color-text-muted) !important;
}
.co-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.co-inline-btn {
  padding: 3px 8px;
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  background: white;
  color: var(--color-text-secondary);
  transition: border-color 0.2s ease, color 0.2s ease;
}
.co-inline-btn:hover {
  border-color: var(--color-ocean-deep);
  color: var(--color-primary-600);
}
.co-inline-btn-success {
  border-color: var(--color-success-400);
  color: var(--color-success-600);
}
.co-inline-btn-success:hover {
  background: var(--color-success-50);
}
.co-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.co-file-inline {
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.co-file-inline-success {
  color: var(--color-success-600);
}

/* ===== 类型切换 ===== */
.co-type-switch {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.co-type-btn {
  padding: 5px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-type-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.co-type-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* ===== 表单 ===== */
.co-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}
.co-form-group {
  margin-bottom: 14px;
}
.co-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}
.co-required {
  color: var(--color-danger-500);
}
.co-textarea {
  width: 100%;
  border: 2px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 14px;
  resize: vertical;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
}
.co-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.co-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.co-textarea::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

/* ===== 抵扣 ===== */
.co-deduct-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}
.co-btn-deduct {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light);
  border-radius: 9px;
  background: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.3s ease, color 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-secondary);
}
.co-btn-deduct:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}
.co-btn-deduct.active {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  border-color: var(--color-primary-400);
}
.co-deduct-display {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 10px;
  border: 2px dashed var(--color-border-light);
  background: var(--color-surface, #f8fafc);
  cursor: pointer;
  transition: border-color 0.3s ease, background 0.3s ease;
  color: var(--color-text-secondary);
  font-family: inherit;
  line-height: inherit;
}
.co-deduct-display:hover {
  border-color: var(--color-primary-400);
  background: var(--color-primary-50);
}
.co-deduct-display strong {
  color: var(--color-primary-600);
}
.co-deduct-info {
  margin-top: 6px;
  padding: 6px 0;
}
.co-deduct-info small {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>

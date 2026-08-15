<template>
  <div class="pd-col-title"><FontAwesomeIcon icon="edit" aria-hidden="true" /> 产品信息</div>
  <div class="pd-col-scroll">
    <!-- 产品基本信息 -->
    <div class="pd-section">
      <form @submit.prevent="handleAdd">
        <div class="pd-form-group">
          <label class="pd-label">产品名称</label>
          <div class="pd-input-wrap">
            <FontAwesomeIcon icon="tag" class="pd-input-icon" aria-hidden="true" />
            <input v-model="form.name" type="text" class="pd-input" required placeholder="例如：小熊毛绒玩具" name="product-name" autocomplete="off" />
          </div>
        </div>
        <div class="pd-form-group">
          <label class="pd-label">69码</label>
          <div class="pd-input-wrap">
            <FontAwesomeIcon icon="barcode" class="pd-input-icon" aria-hidden="true" />
            <input v-model="form.barcode" type="text" class="pd-input" placeholder="例如：6958085574210" name="barcode" autocomplete="off" />
          </div>
        </div>
        <div class="pd-form-group">
          <label class="pd-label">产品价格</label>
          <div class="pd-input-wrap">
            <FontAwesomeIcon icon="yen-sign" class="pd-input-icon" aria-hidden="true" />
            <input v-model.number="form.price" type="number" class="pd-input" step="0.01" min="0" placeholder="请输入产品价格" name="price" autocomplete="off" />
          </div>
        </div>
        <div class="pd-form-group">
          <label class="pd-label">工厂</label>
          <div class="pd-input-wrap">
            <FontAwesomeIcon icon="industry" class="pd-input-icon" aria-hidden="true" />
            <select v-model="form.factory" class="pd-input pd-select" name="factory">
              <option value="" disabled>请选择工厂</option>
              <option v-for="f in factoryOptions" :key="f" :value="f">{{ f }}</option>
            </select>
          </div>
        </div>
        <div class="pd-form-group">
          <label class="pd-label">产品图片</label>
          <div
            class="pd-section-header pd-droppable"
            :class="{ 'pd-drag-over': imageDragOver }"
            @click="imageInputRef?.click()"
            @dragover.prevent="imageDragOver = true"
            @dragleave="imageDragOver = false"
            @drop.prevent="onImageDrop"
          >
            <label class="form-label pd-droppable-label">
              <FontAwesomeIcon icon="image" class="label-icon" aria-hidden="true" />
              <template v-if="form.image">
                <span class="pd-file-inline pd-file-inline-success">
                  <img :src="resolveStaticUrl(form.image)" class="pd-thumb-preview" @click.stop="emit('open-image', form.image)" />
                  <button type="button" class="pd-thumb-remove" @click.stop="form.image = ''" aria-label="关闭"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
                </span>
              </template>
              <span v-else>拖拽文件到标题栏 · 支持 JPG / PNG / GIF</span>
            </label>
            <input ref="imageInputRef" type="file" style="display: none" accept="image/*" name="image" @change="onImageSelect" />
          </div>
        </div>
      </form>
    </div>

    <!-- 产品上传管理 -->
    <div class="pd-section-label"><FontAwesomeIcon icon="file-import" aria-hidden="true" /> 批量导入</div>
    <div
      class="pd-section-header pd-droppable"
      :class="{ 'pd-drag-over': excelDragOver }"
      @click="excelInputRef?.click()"
      @dragover.prevent="excelDragOver = true"
      @dragleave="excelDragOver = false"
      @drop.prevent="onExcelDrop"
    >
      <label class="form-label pd-droppable-label">
        <FontAwesomeIcon icon="file-excel" class="label-icon" aria-hidden="true" />
        <span v-if="excelFile" class="pd-file-inline pd-file-inline-success"><FontAwesomeIcon icon="file-excel" />{{ excelFile.name }}</span>
        <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
      </label>
      <div class="pd-inline-actions">
        <button class="pd-inline-btn" @click.stop="downloadTemplate">模板</button>
        <button class="pd-inline-btn pd-inline-btn-success" :disabled="!excelFile" @click.stop="handleBatchImport">
          {{ importing ? '导入中…' : '导入' }}
        </button>
      </div>
      <input ref="excelInputRef" type="file" style="display: none" accept=".xlsx,.xls" name="file" @change="onExcelSelect" />
    </div>

    <button type="button" class="pd-btn pd-btn-primary w-full justify-center" style="margin-top: 15px" :disabled="submitting" @click="handleAdd">
      <FontAwesomeIcon icon="plus" class="me-2" aria-hidden="true" />{{ submitting ? '添加中…' : '添加产品' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { productApi } from '@/api'
import { upload, download, resolveStaticUrl } from '@/api/request'
import { uploadImage } from '../composables/useImageUpload'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

defineProps<{
  factoryOptions: readonly string[]
}>()

const emit = defineEmits<{
  'open-image': [src: string]
}>()

const queryClient = useQueryClient()

// ===== 添加产品 =====
const submitting = ref(false)
const form = reactive({ name: '', barcode: '', price: 0, factory: '', image: '' })
const imageInputRef = ref<HTMLInputElement | null>(null)
const imageDragOver = ref(false)

function onImageSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  uploadImageFile(file)
}

function onImageDrop(e: DragEvent) {
  imageDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) uploadImageFile(file)
}

function uploadImageFile(file: File) {
  uploadImage(file, (url) => { form.image = url })
}

async function handleAdd() {
  const trimmedName = form.name.trim()
  if (!trimmedName) return
  submitting.value = true
  try {
    await productApi.create({
      name: trimmedName,
      barcode: form.barcode || undefined,
      price: form.price ?? undefined,
      factory: form.factory || undefined,
      image: form.image || undefined,
    })
    showToast('添加成功', 'success')
    Object.assign(form, { name: '', barcode: '', price: 0, factory: '', image: '' })
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '添加失败'), 'error')
  } finally {
    submitting.value = false
  }
}

// ===== Excel批量导入 =====
const excelFile = ref<File | null>(null)
const excelInputRef = ref<HTMLInputElement | null>(null)
const excelDragOver = ref(false)
const importing = ref(false)

function onExcelSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) handleExcelFile(file)
}
function onExcelDrop(e: DragEvent) {
  excelDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) handleExcelFile(file)
}

function handleExcelFile(file: File) {
  const name = file.name.toLowerCase()
  if (!name.endsWith('.xlsx') && !name.endsWith('.xls')) { showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error'); return }
  excelFile.value = file
}

async function handleBatchImport() {
  if (!excelFile.value) return
  importing.value = true
  const formData = new FormData()
  formData.append('file', excelFile.value)
  try {
    await upload('/batch/import-products', formData)
    showToast('导入成功', 'success')
    excelFile.value = null
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '导入失败'), 'error')
  } finally {
    importing.value = false
  }
}

function downloadTemplate() {
  download('/batch/download-template', '产品导入模板.xlsx')
}
</script>

<style scoped>
.pd-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 20px;
  height: 52px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}
.pd-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}
.pd-col-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

/* ===== 区块 ===== */
.pd-section {
  margin-bottom: 20px;
}

/* ===== 表单 ===== */
.pd-form-group {
  margin-bottom: 16px;
}
.pd-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
  line-height: 1.4;
}
.pd-input-wrap {
  position: relative;
}
.pd-input-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-secondary);
  font-size: 14px;
  z-index: 10;
  pointer-events: none;
}
.pd-input {
  width: 100%;
  padding: 8px 12px 8px 36px;
  font-size: 14px;
  line-height: 1.5;
  color: var(--color-text);
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
}
.pd-input:focus {
  background: white;
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.pd-select {
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
  padding-right: 32px;
  background-image: url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
  background-size: 12px;
  cursor: pointer;
}
.pd-select:disabled { background-color: var(--color-surface, #f8fafc); cursor: not-allowed; }

/* ===== 按钮 ===== */
.pd-btn {
  padding: 7px 14px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 9px;
  border: 2px solid var(--color-border-light);
  background: white;
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  line-height: 1.4;
}
.pd-btn:hover { transform: translateY(-1px); }
.pd-btn:active { transform: translateY(0); }
.pd-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
.pd-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  color: white;
  border-color: var(--color-primary-500);
}
.pd-btn-primary:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(59,130,246,0.3); }

/* ===== 上传区（droppable-header 风格） ===== */
.pd-section-header {
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
.pd-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: var(--color-slate-50);
}
.pd-droppable { cursor: pointer; }
.pd-droppable.pd-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
.pd-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
}
.pd-droppable-label {
  display: flex !important;
  margin-bottom: 0;
  cursor: pointer;
  font-size: 14px !important;
  font-weight: 400 !important;
  color: var(--color-text-muted) !important;
  align-items: center;
}
.pd-droppable-label .label-icon {
  color: var(--color-text-muted) !important;
}
.pd-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.pd-inline-btn {
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
.pd-inline-btn:hover {
  border-color: var(--color-ocean-deep);
  color: var(--color-primary-600);
}
.pd-inline-btn-success {
  border-color: var(--color-success-400);
  color: var(--color-success-600);
}
.pd-inline-btn-success:hover {
  background: var(--color-success-50);
}
.pd-inline-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.pd-file-inline {
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.pd-file-inline-success {
  color: var(--color-success-600);
}
.pd-thumb-preview {
  height: 28px;
  width: 28px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--color-border-light);
}
.pd-thumb-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: rgba(0,0,0,0.4);
  color: white;
  font-size: 9px;
  cursor: pointer;
  margin-left: 2px;
  transition: background 0.2s ease;
}
.pd-thumb-remove:hover { background: rgba(0,0,0,0.7); }
</style>

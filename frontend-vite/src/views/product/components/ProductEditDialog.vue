<template>
  <Teleport to="body">
    <div v-if="editDialogVisible" class="pd-overlay" @click.self="editDialogVisible = false">
      <div class="bom-modal-content edit-modal-dialog">
        <div class="bom-modal-header">
          <div class="bom-modal-header-left">
            <h5 class="bom-modal-title"><FontAwesomeIcon icon="edit" aria-hidden="true" /><span>编辑产品 - {{ editForm.name }}</span></h5>
          </div>
          <button class="bom-modal-close" aria-label="关闭" @click="editDialogVisible = false"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
        </div>
        <div class="bom-modal-body">
          <div class="edit-modal-content">
            <div class="pd-form-group">
              <label class="pd-label">产品名称 <span class="required">*</span></label>
              <div class="pd-input-wrap">
                <FontAwesomeIcon icon="tag" class="pd-input-icon" aria-hidden="true" />
                <input v-model="editForm.name" type="text" class="pd-input" required placeholder="请输入产品名称" name="product-name" autocomplete="off" aria-label="请输入产品名称" />
              </div>
            </div>
            <div class="pd-form-group">
              <label class="pd-label">69码/商品条码</label>
              <div class="pd-input-wrap">
                <FontAwesomeIcon icon="barcode" class="pd-input-icon" aria-hidden="true" />
                <input v-model="editForm.barcode" type="text" class="pd-input" placeholder="例如：6958085574210" name="barcode" autocomplete="off" aria-label="例如：6958085574210" />
              </div>
            </div>
            <div class="pd-form-group">
              <label class="pd-label">产品价格</label>
              <div class="pd-input-wrap">
                <FontAwesomeIcon icon="yen-sign" class="pd-input-icon" aria-hidden="true" />
                <input v-model.number="editForm.price" type="number" class="pd-input" step="0.01" min="0" placeholder="请输入产品价格" name="price" autocomplete="off" aria-label="请输入产品价格" />
              </div>
            </div>
            <div class="pd-form-group">
              <label class="pd-label">工厂</label>
              <div class="pd-input-wrap">
                <FontAwesomeIcon icon="industry" class="pd-input-icon" aria-hidden="true" />
                <select v-model="editForm.factory" class="pd-input pd-select" name="edit-factory" aria-label="工厂">
                  <option value="" disabled>请选择工厂</option>
                  <option v-for="f in factoryOptions" :key="f" :value="f">{{ f }}</option>
                </select>
              </div>
            </div>
            <div class="pd-form-group">
              <label class="pd-label">所属客户</label>
              <ProductCustomerSelect v-model="editForm.customerIds" :options="customerOptions" />
            </div>
            <div class="pd-form-group">
              <label class="pd-label">产品图片</label>
              <div
                ref="editDropZoneRef"
                class="pd-section-header pd-droppable"
                :class="{ 'pd-drag-over': editDragOver || editPasteFlash }"
                title="点击选择、拖拽或粘贴图片"
                @click="editImageInputRef?.click()"
                @dragover.prevent="onEditDragOver"
                @dragleave="editDragOver = false"
                @drop.prevent="onEditDrop"
              >
                <label class="form-label pd-droppable-label">
                  <FontAwesomeIcon icon="image" class="label-icon" aria-hidden="true" />
                  <template v-if="editForm.image">
                    <span class="pd-file-inline pd-file-inline-success">
                      <img loading="lazy" :src="resolveStaticUrl(editForm.image)" class="pd-thumb-preview" alt="产品图片" @click.stop="emit('open-image', editForm.image)" />
                      <button type="button" class="pd-thumb-remove" aria-label="关闭" @click.stop="editForm.image = ''"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
                    </span>
                  </template>
                  <span v-else>点击选择 / 拖拽 / 粘贴图片 · 支持 {{ ALLOWED_IMAGE_HINT }}</span>
                </label>
                <input ref="editImageInputRef" type="file" style="display: none" accept="image/*" name="image" @change="onEditImageSelect" />
              </div>
            </div>
          </div>
        </div>
        <div class="bom-modal-footer">
          <button class="bom-btn-cancel" @click="editDialogVisible = false">取消</button>
          <button class="bom-btn-save" :disabled="editSubmitting" @click="handleEditSave">
            <FontAwesomeIcon icon="save" aria-hidden="true" />{{ editSubmitting ? '保存中…' : '保存修改' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onBeforeUnmount } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { productApi } from '@/api'
import { resolveStaticUrl } from '@/api/request'
import { useCatalogStore } from '@/stores/catalog'
import { uploadImage, ALLOWED_IMAGE_HINT } from '../composables/useImageUpload'
import { useImagePaste } from '@/composables/useImagePaste'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import ProductCustomerSelect from './ProductCustomerSelect.vue'
import type { ProductCustomerRef } from '@/types'

interface Product {
  id: number
  name: string
  barcode: string
  price: number
  image: string | null
  factory?: string
  current_stock?: number
  customers?: ProductCustomerRef[]
}

defineProps<{
  factoryOptions: readonly string[]
}>()

const emit = defineEmits<{
  'open-image': [src: string]
}>()

const queryClient = useQueryClient()

// 客户下拉数据源：目录 store 统一缓存（与订单/出货页同源）
const catalogStore = useCatalogStore()
catalogStore.ensureActiveCustomerNames().catch(() => {
  // 加载失败保持空列表，下次进入视图时重试
})

/** 当前编辑的产品自己挂着的客户（可能含已停用、不在 activeNames 里的） */
const ownCustomers = ref<ProductCustomerRef[]>([])
/**
 * 选项 = 启用客户 ∪ 本产品已挂客户。
 * 不并进来会出事：客户停用后 activeNames 里没有它，多选控件只能显示「客户 #id」，
 * 用户看不清；而一旦在保存时按选项过滤，就会把这条归属静默抹掉（= 放开给所有客户）。
 */
const customerOptions = computed<ProductCustomerRef[]>(() => {
  const byId = new Map<number, ProductCustomerRef>()
  for (const c of catalogStore.activeCustomerNames) byId.set(c.id, { id: c.id, name: c.name })
  for (const c of ownCustomers.value) if (!byId.has(c.id)) byId.set(c.id, c)
  return [...byId.values()]
})

// ===== 编辑产品弹窗 =====
const editDialogVisible = ref(false)
const editSubmitting = ref(false)
const editForm = reactive({ id: 0, name: '', barcode: '', price: 0, factory: '', image: '', customerIds: [] as number[] })
const editImageInputRef = ref<HTMLInputElement | null>(null)
const editDropZoneRef = ref<HTMLElement | null>(null)
const editDragOver = ref(false)
const editPasteFlash = ref(false)

let editPasteFlashTimer: ReturnType<typeof setTimeout> | undefined

function flashEditPasteFeedback() {
  editPasteFlash.value = true
  clearTimeout(editPasteFlashTimer)
  editPasteFlashTimer = setTimeout(() => { editPasteFlash.value = false }, 600)
}

// 弹窗优先级高于左侧新增表单：弹窗打开时只有它响应粘贴
useImagePaste({
  target: editDropZoneRef,
  onFile: (file) => {
    flashEditPasteFeedback()
    uploadEditImage(file)
  },
  enabled: () => editDialogVisible.value,
  priority: 10,
})

onBeforeUnmount(() => clearTimeout(editPasteFlashTimer))

function open(row: Product) {
  ownCustomers.value = row.customers ?? []
  Object.assign(editForm, {
    id: row.id, name: row.name, barcode: row.barcode, price: row.price,
    factory: row.factory || '', image: row.image || '',
    customerIds: (row.customers ?? []).map((c) => c.id),
  })
  editDialogVisible.value = true
}

function onEditImageSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 清空以便同一文件可重复选择
  if (file) uploadEditImage(file)
}

/** 仅在拖入真实文件时高亮，与粘贴反馈语义保持一致 */
function onEditDragOver(e: DragEvent) {
  if (e.dataTransfer?.types.includes('Files')) editDragOver.value = true
}

function onEditDrop(e: DragEvent) {
  editDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file) uploadEditImage(file)
}

function uploadEditImage(file: File) {
  uploadImage(file, (url) => { editForm.image = url })
}

async function handleEditSave() {
  if (!editForm.name.trim()) { showToast('请输入产品名称', 'warning'); return }
  editSubmitting.value = true
  try {
    await productApi.update(editForm.id, { name: editForm.name, barcode: editForm.barcode, price: editForm.price, factory: editForm.factory, image: editForm.image, customer_ids: editForm.customerIds })
    showToast('保存成功', 'success')
    editDialogVisible.value = false
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '保存失败'), 'error')
  } finally {
    editSubmitting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
/* ===== 模态框遮罩 ===== */
.pd-overlay {
  position: fixed; inset: 0; z-index: 1050; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; padding: 16px;
}

.edit-modal-content { padding: 20px; }

/* ===== 表单 ===== */
.pd-form-group { margin-bottom: 16px; }
.pd-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
  line-height: 1.4;
}
.required { color: var(--color-danger-500); font-weight: 700; }
.pd-input-wrap { position: relative; }
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

/* ===== 上传区 ===== */
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

/* ===== BOM模态框（编辑弹窗复用） ===== */
.bom-modal-content {
  border-radius: 18px; border: none; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  overflow: hidden; background: white;
}
.edit-modal-dialog { max-width: 800px; width: 95vw; max-height: 90vh; display: flex; flex-direction: column; }
.bom-modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 28px; background: transparent;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.bom-modal-header-left { flex: 1; }
.bom-modal-title {
  display: flex; align-items: center; gap: 10px;
  font-size: 16px; font-weight: 700; color: var(--color-text); margin: 0;
}
.bom-modal-title i { color: var(--color-primary-500); }
.bom-modal-close {
  width: 36px; height: 36px; border: none; background: var(--color-surface, #f8fafc);
  border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: var(--color-text-secondary); font-size: 16px; transition: background 0.3s ease, color 0.3s ease, transform 0.3s ease;
}
.bom-modal-close:hover { background: var(--color-border-light, #e2e8f0); color: var(--color-text); transform: rotate(90deg); }
.bom-modal-body { padding: 0; background: var(--color-surface, #f8fafc); overflow-y: auto; flex: 1; }
.bom-modal-footer {
  display: flex; justify-content: flex-end; align-items: center; gap: 10px;
  padding: 20px 28px; background: white;
  border-top: 1px solid var(--color-border-light, #e2e8f0);
}
.bom-btn-cancel {
  padding: 10px 20px; background: white; color: var(--color-text);
  border: 2px solid var(--color-border-light, #e2e8f0); border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.3s ease, transform 0.3s ease;
}
.bom-btn-cancel:hover { background: var(--color-surface, #f8fafc); transform: translateY(-1px); }
.bom-btn-save {
  padding: 10px 20px; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  color: white; border: 2px solid var(--color-primary-500); border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: transform 0.3s ease, box-shadow 0.3s ease;
  display: flex; align-items: center; gap: 6px;
}
.bom-btn-save:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.3); }
.bom-btn-save:disabled { opacity: 0.4; cursor: not-allowed; }
</style>

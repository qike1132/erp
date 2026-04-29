<template>
  <div class="product-edit-page">
    <div class="edit-layout">
      <div class="card-elegant">
        <div class="card-header-elegant">
          <div class="card-header-content">
            <button class="btn-back-elegant" @click="$router.push('/product')">
              <i class="fas fa-arrow-left"></i>
            </button>
            <h3 class="card-title-elegant">编辑产品</h3>
          </div>
        </div>
        <div class="card-body-elegant">
          <div v-if="loading" class="loading-state">
            <i class="fas fa-spinner fa-spin"></i> 加载中...
          </div>
          <form v-else @submit.prevent="handleSave">
            <div class="form-group-spacious">
              <label class="form-label-elegant">产品名称 <span class="required">*</span></label>
              <div class="input-wrapper">
                <i class="fas fa-tag input-icon"></i>
                <input v-model="form.name" type="text" class="form-control-elegant" required placeholder="请输入产品名称" />
              </div>
            </div>
            <div class="form-group-spacious">
              <label class="form-label-elegant">69码/商品条码</label>
              <div class="input-wrapper">
                <i class="fas fa-barcode input-icon"></i>
                <input v-model="form.barcode" type="text" class="form-control-elegant" placeholder="例如：6958085574210" />
              </div>
            </div>
            <div class="form-group-spacious">
              <label class="form-label-elegant">产品价格</label>
              <div class="input-wrapper">
                <i class="fas fa-yen-sign input-icon"></i>
                <input v-model.number="form.price" type="number" class="form-control-elegant" step="0.01" min="0" placeholder="请输入产品价格" />
              </div>
            </div>
            <div class="form-group-spacious">
              <label class="form-label-elegant">产品图片</label>
              <div
                class="upload-zone-elegant"
                tabindex="0"
                @click="triggerUpload"
                @dragover.prevent="onDragOver"
                @dragleave="onDragLeave"
                @drop.prevent="onDrop"
              >
                <template v-if="form.image">
                  <div class="image-preview-wrapper">
                    <img :src="form.image" alt="预览" class="image-preview-img" @click.stop="openImageModal" />
                    <button type="button" class="image-remove-btn" @click.stop="form.image = ''"><i class="fas fa-times"></i></button>
                  </div>
                </template>
                <template v-else>
                  <div class="upload-zone-content-elegant">
                    <i class="fas fa-plus upload-icon-big"></i>
                    <p class="upload-text">拖拽图片到这里</p>
                    <p class="upload-subtext">或点击选择图片</p>
                  </div>
                </template>
                <input ref="fileInputRef" type="file" style="display: none" accept="image/*" @change="onFileSelect" />
              </div>
            </div>
            <div class="form-actions">
              <button type="submit" class="btn-elegant btn-primary-elegant" :disabled="submitting">
                <i class="fas fa-save me-2"></i>{{ submitting ? '保存中...' : '保存修改' }}
              </button>
              <button type="button" class="btn-elegant btn-outline-secondary-elegant" @click="$router.push('/product')">取消</button>
            </div>
          </form>
        </div>
      </div>
    </div>

    <!-- 图片查看模态框 -->
    <Teleport to="body">
      <div v-if="imageModalVisible" class="modal-overlay" @click.self="imageModalVisible = false">
        <div class="modal-content-elegant modal-image-dialog">
          <div class="modal-header-elegant">
            <h5 class="modal-title-elegant">产品图片</h5>
            <button class="btn-close-elegant" @click="imageModalVisible = false"><i class="fas fa-times"></i></button>
          </div>
          <div class="modal-body-elegant">
            <img :src="form.image" class="modal-image-elegant" />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { productApi } from '@/api'
import { upload } from '@/api/request'
import { showToast } from '@/composables/useToast'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const submitting = ref(false)
const form = reactive({ name: '', barcode: '', price: 0, image: '' })

// 图片模态框
const imageModalVisible = ref(false)
function openImageModal() { imageModalVisible.value = true }

// 文件上传
const fileInputRef = ref<HTMLInputElement | null>(null)
function triggerUpload() { fileInputRef.value?.click() }

function onFileSelect(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) uploadImageFile(file)
}

function onDragOver(e: DragEvent) {
  const el = e.currentTarget as HTMLElement
  el.style.borderColor = 'var(--color-primary-500)'
  el.style.background = 'linear-gradient(135deg, var(--color-primary-50) 0%, var(--color-slate-50) 100%)'
}
function onDragLeave(e: DragEvent) {
  const el = e.currentTarget as HTMLElement
  el.style.borderColor = 'var(--color-slate-300)'
  el.style.background = 'var(--color-surface-card)'
}
function onDrop(e: DragEvent) {
  const el = e.currentTarget as HTMLElement
  el.style.borderColor = 'var(--color-slate-300)'
  el.style.background = 'var(--color-surface-card)'
  const file = e.dataTransfer?.files[0]
  if (file) uploadImageFile(file)
}

function uploadImageFile(file: File) {
  const allowed = ['image/jpeg', 'image/png', 'image/gif']
  if (!allowed.includes(file.type)) { showToast('仅支持 JPG/PNG/GIF 格式', 'error'); return }
  if (file.size > 5 * 1024 * 1024) { showToast('文件大小不能超过 5MB', 'error'); return }
  const formData = new FormData()
  formData.append('file', file)
  upload<{ url: string }>('/auth/upload', formData)
    .then(data => { if (data.url) form.image = data.url })
    .catch(() => showToast('上传失败', 'error'))
}

// 加载产品数据
onMounted(async () => {
  try {
    const id = Number(route.params.id)
    const data = (await productApi.detail(id)) as any
    Object.assign(form, {
      name: data.name,
      barcode: data.barcode ?? '',
      price: data.price ?? 0,
      image: data.image ?? '',
    })
  } catch {
    showToast('加载产品信息失败', 'error')
    router.push('/product')
  } finally {
    loading.value = false
  }
})

// 保存
async function handleSave() {
  if (!form.name.trim()) { showToast('请输入产品名称', 'warning'); return }
  submitting.value = true
  try {
    await productApi.update(Number(route.params.id), form)
    showToast('保存成功', 'success')
    router.push('/product')
  } catch (err: any) {
    showToast(err.response?.data?.detail || '保存失败', 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
/* 返回按钮 */
.btn-back-elegant {
  width: 44px; height: 44px; border-radius: 12px; border: 2px solid var(--color-slate-200); background: var(--color-slate-50); color: var(--color-slate-500);
  display: flex; align-items: center; justify-content: center; font-size: 1rem; cursor: pointer; transition: all 0.3s ease;
}
.btn-back-elegant:hover { background: var(--color-slate-200); color: var(--color-slate-700); transform: translateY(-1px); }

/* 编辑布局 */
.edit-layout { max-width: 700px; }

/* 卡片 */
.card-elegant {
  background: var(--color-surface-card); border-radius: 20px; border: 1px solid var(--color-slate-200);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4,0,0.2,1); overflow: hidden;
}
.card-elegant:hover { box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12); transform: translateY(-6px); }
.card-header-elegant { padding: 1.75rem 2rem; background: transparent; border-bottom: 1px solid var(--color-border-light, #f1f5f9); }
.card-header-content { display: flex; align-items: center; gap: 0.75rem; }
.card-title-elegant { font-size: 1.125rem; font-weight: 600; color: var(--color-slate-700); line-height: 1.3; margin: 0; }
.card-body-elegant { padding: 2rem; }

/* 图标圆圈 */
.icon-circle { width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 1.25rem; }
.icon-circle-blue { background: linear-gradient(135deg, var(--color-primary-100) 0%, var(--color-primary-200) 100%); color: var(--color-primary-700); }

/* 表单 */
.form-group-spacious { margin-bottom: 2rem; }
.form-label-elegant { display: block; font-size: 0.9375rem; font-weight: 500; color: var(--color-slate-600); margin-bottom: 0.75rem; line-height: 1.4; }
.required { color: var(--color-danger-500); font-weight: 700; }
.input-wrapper { position: relative; }
.input-icon { position: absolute; left: 1rem; top: 50%; transform: translateY(-50%); color: var(--color-slate-400); font-size: 1rem; z-index: 10; }
.form-control-elegant {
  width: 100%; padding: 0.875rem 1rem 0.875rem 3rem; font-size: 1rem; line-height: 1.5; color: var(--color-slate-700);
  background: var(--color-slate-50); border: 2px solid var(--color-slate-200); border-radius: 14px; transition: all 0.3s ease; outline: none;
}
.form-control-elegant:focus { background: var(--color-surface-card); border-color: var(--color-primary-500); box-shadow: 0 0 0 4px rgba(59,130,246,0.1); }

/* 按钮 */
.btn-elegant {
  padding: 0.75rem 1.25rem; font-size: 0.9375rem; font-weight: 500; border-radius: 12px; border: 2px solid transparent;
  transition: all 0.3s ease; display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer;
}
.btn-elegant:hover { transform: translateY(-1px); }
.btn-elegant:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
.btn-primary-elegant { background: linear-gradient(135deg, var(--color-primary-500) 0%, var(--color-primary-600) 100%); color: var(--color-text-inverse); border-color: var(--color-primary-500); }
.btn-primary-elegant:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(59,130,246,0.3); }
.btn-outline-secondary-elegant { background: var(--color-surface-card); color: var(--color-slate-500); border-color: var(--color-slate-200); }
.btn-outline-secondary-elegant:hover { background: var(--color-slate-50); border-color: var(--color-slate-300); }
.me-2 { margin-right: 0.5rem; }

/* 表单操作栏 */
.form-actions { display: flex; gap: 0.75rem; margin-top: 2rem; padding-top: 1.5rem; border-top: 1px solid var(--color-slate-100); }

/* 上传区 */
.upload-zone-elegant {
  border: 2px dashed var(--color-slate-300); border-radius: 16px; padding: 2.5rem 1.5rem; text-align: center; background: var(--color-surface-card);
  cursor: pointer; transition: all 0.3s ease;
}
.upload-zone-elegant:hover, .upload-zone-elegant:focus-within {
  border-color: var(--color-primary-500); background: linear-gradient(135deg, var(--color-primary-50) 0%, var(--color-slate-50) 100%); transform: translateY(-6px);
}
.upload-zone-content-elegant { display: flex; flex-direction: column; align-items: center; justify-content: center; }
.upload-icon-big { font-size: 2.5rem; color: var(--color-slate-400); margin-bottom: 0.75rem; }
.upload-text { font-size: 1rem; color: var(--color-slate-500); font-weight: 500; margin: 0; line-height: 1.4; }
.upload-subtext { font-size: 0.875rem; color: var(--color-slate-400); margin: 0; line-height: 1.4; }
.image-preview-wrapper { position: relative; display: inline-block; }
.image-preview-img { max-width: 100%; max-height: 240px; object-fit: contain; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); cursor: pointer; }
.image-remove-btn {
  position: absolute; top: 8px; right: 8px; width: 28px; height: 28px; border-radius: 50%; border: none;
  background: rgba(0,0,0,0.5); color: var(--color-text-inverse); cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 12px;
}

/* 加载状态 */
.loading-state { padding: 3rem 0; text-align: center; color: var(--color-slate-400); }

/* 模态框 */
.modal-overlay { position: fixed; inset: 0; z-index: 1050; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; padding: 1rem; }
.modal-content-elegant { border-radius: 24px; border: none; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); background: var(--color-surface-card); overflow: hidden; }
.modal-image-dialog { max-width: 90vw; width: 800px; }
.modal-header-elegant { padding: 1.5rem 2rem; background: transparent; border-bottom: 1px solid var(--color-border-light, #f1f5f9); display: flex; justify-content: space-between; align-items: center; }
.modal-title-elegant { font-size: 1.25rem; font-weight: 600; color: var(--color-slate-700); }
.btn-close-elegant { width: 40px; height: 40px; border-radius: 10px; border: none; background: var(--color-slate-100); color: var(--color-text-secondary); display: flex; align-items: center; justify-content: center; font-size: 1.25rem; transition: all 0.2s ease; cursor: pointer; }
.btn-close-elegant:hover { background: var(--color-slate-200); color: var(--color-slate-700); }
.modal-body-elegant { padding: 2rem; background: var(--color-slate-50); display: flex; align-items: center; justify-content: center; min-height: 60vh; }
.modal-image-elegant { max-width: 100%; max-height: 80vh; object-fit: contain; border-radius: 16px; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }
</style>

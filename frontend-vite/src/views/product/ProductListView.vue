<template>
  <div class="pd-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->

      <!-- 双栏主体 -->
      <div class="page-card-body">
        <!-- 左栏：产品信息 -->
        <div class="pd-col">
          <ProductForm :factory-options="FACTORY_OPTIONS" @open-image="openImageModal" />
        </div>

        <!-- 右栏：产品列表 -->
        <div class="pd-col">
          <ProductTable
            :action-id="actionId"
            @open-bom="openBomEditor"
            @open-edit="openEditEditor"
            @delete="handleDelete"
            @open-image="openImageModal"
          />
        </div>
      </div>
    </div>

    <!-- 图片查看模态框（共享 UiDialog：Esc / 焦点陷阱 / 滚动锁内建；点遮罩空白不关闭，2026-10-14 约定） -->
    <UiDialog
      :open="imageModalVisible"
      max-width-class="max-w-[800px]"
      overlay-z-class="z-[var(--z-page-modal)]"
      content-z-class="z-[var(--z-page-modal)] pd-modal-img-card"
      :body-padded="false"
      @update:open="imageModalVisible = $event"
    >
      <template #title>
        <span class="pd-modal-title">产品图片</span>
      </template>
      <div class="pd-modal-body">
        <img loading="lazy" :src="resolveStaticUrl(imageModalSrc)" class="pd-modal-img-view" alt="产品图片" />
      </div>
    </UiDialog>

    <!-- BOM配置模态框 -->
    <BomEditor
      ref="bomEditorRef"
      @saved="handleBomResumeSaved"
      @closed="handleBomResumeClosed"
    />

    <!-- 编辑产品模态框 -->
    <ProductEditDialog ref="editDialogRef" :factory-options="FACTORY_OPTIONS" @open-image="openImageModal" />

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
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { productApi } from '@/api'
import { resolveStaticUrl } from '@/api/request'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import ProductForm from './components/ProductForm.vue'
import ProductTable from './components/ProductTable.vue'
import BomEditor from './components/BomEditor.vue'
import ProductEditDialog from './components/ProductEditDialog.vue'
import { useProductBomResume } from './composables/useProductBomResume'

interface Product {
  id: number
  name: string
  barcode: string
  price: number
  image: string | null
  factory?: string
  current_stock?: number
}

// 工厂下拉选项（与后端 VALID_FACTORIES 保持一致）
const FACTORY_OPTIONS = ['东莞', '湖北'] as const

// ===== 核心状态 =====
const actionId = ref<number | null>(null)
const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

const bomEditorRef = ref<InstanceType<typeof BomEditor> | null>(null)
const editDialogRef = ref<InstanceType<typeof ProductEditDialog> | null>(null)
const bomResume = useProductBomResume(bomEditorRef)
bomResume.watchResumeRoute()

async function handleBomResumeSaved(payload: { product_id: number }) {
  await bomResume.onSaved(payload.product_id)
}

async function handleBomResumeClosed() {
  await bomResume.onClosed()
}

// ===== 删除产品 =====
async function handleDelete(row: Product) {
  if (!(await confirmDialog.confirm(`确定要删除产品"${row.name}"吗？`))) return
  actionId.value = row.id
  try {
    await productApi.delete(row.id)
    showToast('删除成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['products-list'] })
  } catch (err: unknown) {
    showToast(getErrorMessage(err, '删除失败'), 'error')
  } finally {
    actionId.value = null
  }
}

function openBomEditor(p: Product) {
  bomEditorRef.value?.open(p)
}

function openEditEditor(p: Product) {
  editDialogRef.value?.open(p)
}

// ===== 图片查看模态框 =====
const imageModalVisible = ref(false)
const imageModalSrc = ref('')

function openImageModal(src: string) {
  imageModalSrc.value = src
  imageModalVisible.value = true
}
</script>

<style scoped>
/* ===== 容器 ===== */
.pd-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* ===== 主卡片 ===== */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* ===== 卡片头部 ===== */

/* ===== 双栏主体 ===== */
/* 卡片主体样式已迁移到全局 .page-card-body（src/styles/app.css） */
/* 产品页需要 2 列网格布局，覆盖默认 page-card-body */
.page-card-body {
  display: grid;
  grid-template-columns: 1fr 2fr;
  overflow: hidden;
}

/* ===== 栏目 ===== */
.pd-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.pd-col + .pd-col {
  border-left: 1px solid var(--color-border-light, #f1f5f9);
}

/* ===== 图片模态框（外壳由 UiDialog 提供，此处仅保留图片区视觉） ===== */
.pd-modal-title { font-size: 14px; font-weight: 700; color: var(--color-text); }
.pd-modal-body {
  padding: 20px; background: var(--color-surface, #f8fafc);
  display: flex; align-items: center; justify-content: center; min-height: 50vh;
}
.pd-modal-img-view {
  max-width: 100%; max-height: 80vh; object-fit: contain;
  border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}

/* ===== 响应式 ===== */
@media (max-width: 1199.98px) {
  .page-card-body { grid-template-columns: 1fr; }
  .pd-col + .pd-col { border-left: none; border-top: 1px solid var(--color-border-light, #f1f5f9); }
}
</style>

<!-- 卡片元素由 UiDialog 渲染并 portal 到 body，scoped 样式够不到 → 全局维持迁移前的 18px 圆角 -->
<style>
.pd-modal-img-card {
  border-radius: 18px !important;
}
</style>

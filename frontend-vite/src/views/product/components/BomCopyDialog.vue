<template>
  <!-- 共享 UiDialog：Esc / 焦点陷阱 / 滚动锁内建；点遮罩空白不关闭（closeOnOverlayClick 默认 false） -->
  <UiDialog
    :open="open"
    max-width-class="max-w-[1200px]"
    overlay-z-class="z-[var(--z-page-modal)]"
    content-z-class="z-[var(--z-page-modal)] copy-bom-modal-card"
    body-class="copy-bom-body"
    @update:open="open = $event"
  >
    <template #title>
      <FontAwesomeIcon icon="copy" class="text-primary-500" aria-hidden="true" />
      <span>复制BOM表</span>
    </template>
    <div class="mb-4">
      <label class="pd-label mb-2"><FontAwesomeIcon icon="search" class="me-2" aria-hidden="true" />搜索源产品</label>
      <div class="pd-input-wrap">
        <FontAwesomeIcon icon="tag" class="pd-input-icon" aria-hidden="true" />
        <input v-model="searchKeyword" type="text" class="pd-input" placeholder="输入产品名称或条码进行搜索" name="search" autocomplete="off" aria-label="输入产品名称或条码进行搜索" @keydown.enter="emit('search')" />
      </div>
      <div class="mt-2"><button class="pd-btn pd-btn-primary pd-btn-sm" aria-label="搜索" @click="emit('search')"><FontAwesomeIcon icon="search" class="me-2" aria-hidden="true" />搜索</button></div>
    </div>
    <div v-if="products.length > 0" class="mb-4">
      <label class="pd-label mb-2"><FontAwesomeIcon icon="box" class="me-2" aria-hidden="true" />选择源产品</label>
      <div class="copy-bom-product-list">
        <div v-for="product in products" :key="product.id" class="copy-bom-product-item" :class="{ selected: sourceProductId === product.id }" @click="emit('select-product', product)">
          <div>
            <div class="product-name">{{ product.name }}</div>
            <div class="product-barcode">{{ product.barcode ? '条码: ' + product.barcode : '' }}</div>
          </div>
          <span class="product-status" :class="product.has_bom ? 'has-bom' : 'no-bom'">{{ product.has_bom ? '有BOM' : '无BOM' }}</span>
        </div>
      </div>
    </div>
    <BomPreview :preview="preview" />
    <div v-if="preview" class="mb-4">
      <label class="form-check-label">
        <input v-model="overwrite" type="checkbox" class="form-check-input" aria-label="勾选项" />
        <strong>覆盖现有BOM表</strong>
        <span class="text-muted block text-sm">如果目标产品已有BOM表，勾选此项将覆盖原数据</span>
      </label>
    </div>
    <div v-if="progress.visible" class="mb-4">
      <div class="pd-progress"><div class="pd-progress-bar" :style="{ width: progress.percent + '%' }" /></div>
      <p class="pd-progress-text">{{ progress.text }}</p>
    </div>
    <template #footer>
      <button class="bom-btn-cancel" aria-label="取消" @click="open = false">取消</button>
      <button class="bom-btn-save" :disabled="!sourceProductId" aria-label="确认复制" @click="emit('confirm')"><FontAwesomeIcon icon="check" class="me-2" aria-hidden="true" />确认复制</button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import type { BomSearchProduct, BomPreviewStats, ProgressState } from '../composables/bomTypes'
import BomPreview from './BomPreview.vue'
import UiDialog from '@/components/ui/UiDialog.vue'

defineProps<{
  products: BomSearchProduct[]
  sourceProductId: number | null
  preview: BomPreviewStats | null
  progress: ProgressState
}>()

const open = defineModel<boolean>('open', { default: false })
const searchKeyword = defineModel<string>('searchKeyword', { default: '' })
const overwrite = defineModel<boolean>('overwrite', { default: false })

const emit = defineEmits<{
  search: []
  'select-product': [product: BomSearchProduct]
  confirm: []
}>()
</script>

<style scoped>
/* ===== 表单 ===== */
.pd-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
  line-height: 1.4;
}
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
.pd-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
.pd-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  color: white;
  border-color: var(--color-primary-500);
}
.pd-btn-sm { padding: 5px 10px; font-size: 11px; }

/* 尺寸契约（勿改回随内容变化）：弹窗恒定高度 90vh，内容多少只影响内部滚动位置。
   高度 / 圆角 / body 内边距由文件末尾的全局 .copy-bom-modal-card 规则维持
   （卡片与 body 均由 UiDialog 渲染，scoped 样式够不到）。 */
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

/* 进度条 */
.pd-progress { height: 16px; border-radius: 8px; background: var(--color-border-light, #e2e8f0); overflow: hidden; }
.pd-progress-bar { height: 100%; background: linear-gradient(135deg, var(--color-warning-400), var(--color-warning-600)); border-radius: 8px; transition: width 0.3s ease; }
.pd-progress-text { margin-top: 6px; font-size: 12px; color: var(--color-text-secondary); text-align: center; }

/* 复制BOM模态框 */
.copy-bom-product-list { max-height: 200px; overflow-y: auto; }
.copy-bom-product-item {
  padding: 10px 14px; border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px; margin-bottom: 6px; cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease; display: flex; justify-content: space-between; align-items: center;
}
.copy-bom-product-item:hover { border-color: var(--color-primary-300); background: var(--color-primary-50); }
.copy-bom-product-item.selected { border-color: var(--color-success-500); background: var(--color-success-50); }
.copy-bom-product-item .product-name { font-weight: 600; color: var(--color-text); }
.copy-bom-product-item .product-barcode { font-size: 11px; color: var(--color-text-secondary); }
.copy-bom-product-item .product-status { font-size: 11px; padding: 3px 8px; border-radius: 16px; }
.copy-bom-product-item .product-status.has-bom { background: var(--color-success-50); color: var(--color-success-600); }
.copy-bom-product-item .product-status.no-bom { background: var(--color-warning-50); color: var(--color-warning-600); }

/* ===== 工具类 ===== */
.text-muted { color: var(--color-text-secondary); }
.form-check-input { width: 1.125rem; height: 1.125rem; margin-right: 0.5rem; }
.form-check-label { display: flex; align-items: flex-start; gap: 0.5rem; }
</style>

<!-- 卡片与 body 均由 UiDialog 渲染并 portal 到 body，scoped 样式够不到 → 全局维持迁移前观感 -->
<style>
.copy-bom-modal-card {
  border-radius: 18px !important;
  height: 90vh !important;
  min-height: 620px !important;
}
.copy-bom-body {
  padding: 0 !important;
  min-height: 0 !important;
  background: var(--color-surface, #f8fafc) !important;
}
</style>

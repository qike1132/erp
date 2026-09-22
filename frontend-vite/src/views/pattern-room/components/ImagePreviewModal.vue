<template>
  <Teleport to="body">
    <div v-if="image" class="pim-overlay" @click.self="$emit('update:image', null)">
      <div class="pim-modal pim-dialog">
        <div class="pim-header">
          <h5 class="pim-title">产品图片</h5>
          <button class="pim-close" aria-label="关闭" @click="$emit('update:image', null)"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
        </div>
        <div class="pim-body">
          <img loading="lazy" :src="resolveStaticUrl(image)" class="pim-img-view" alt="产品图片" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { resolveStaticUrl } from '@/api/request'

defineProps<{ image: string | null }>()
defineEmits<{ 'update:image': [v: string | null] }>()
</script>

<style>
/* 前缀 pim-（ImagePreviewModal）：全局样式（Teleport 至 body），避免与 PrintDialog 的 pd-* 冲突 */
.pim-overlay {
  position: fixed; inset: 0; z-index: 1050; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; padding: 16px;
}
.pim-modal {
  border-radius: 18px; border: none; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
  background: white; overflow: hidden;
}
.pim-dialog { max-width: 90vw; width: 800px; }
.pim-header {
  padding: 14px 20px; background: transparent;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  display: flex; justify-content: space-between; align-items: center;
}
.pim-title { font-size: 14px; font-weight: 700; color: var(--color-text); }
.pim-close {
  width: 32px; height: 32px; border-radius: 8px; border: none;
  background: var(--color-surface, #f8fafc); color: var(--color-text-secondary);
  display: flex; align-items: center; justify-content: center; font-size: 14px;
  transition: background 0.2s ease, color 0.2s ease; cursor: pointer;
}
.pim-close:hover { background: var(--color-border-light, #e2e8f0); color: var(--color-text); }
.pim-body {
  padding: 20px; background: var(--color-surface, #f8fafc);
  display: flex; align-items: center; justify-content: center; min-height: 50vh;
}
.pim-img-view {
  max-width: 100%; max-height: 80vh; object-fit: contain;
  border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}
</style>
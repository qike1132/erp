<template>
  <div v-if="preview" class="copy-bom-preview-card">
    <div class="preview-header">
      <div>
        <h6 class="mb-0">{{ preview.source_name }}</h6>
        <p class="text-muted text-sm mb-0">条码：{{ preview.source_barcode || '-' }}</p>
      </div>
    </div>
    <div class="preview-stats">
      <div class="preview-stat-item"><div class="text-muted text-sm">物料总数</div><div class="text-2xl font-bold text-primary-500">{{ preview.material_count }}</div></div>
      <div class="preview-stat-item"><div class="text-muted text-sm">角色数</div><div class="text-2xl font-bold">{{ preview.role_count }}</div></div>
      <div class="preview-stat-item"><div class="text-muted text-sm">面料类</div><div class="text-2xl font-bold">{{ preview.fabric_count }}</div></div>
      <div class="preview-stat-item"><div class="text-muted text-sm">填充类</div><div class="text-2xl font-bold">{{ preview.filling_count }}</div></div>
      <div class="preview-stat-item"><div class="text-muted text-sm">辅料/包装</div><div class="text-2xl font-bold">{{ preview.accessory_count }}</div></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { BomPreviewStats } from '../composables/bomTypes'

defineProps<{
  preview: BomPreviewStats | null
}>()
</script>

<style scoped>
.copy-bom-preview-card {
  border: 1px solid var(--color-primary-100); background: var(--color-primary-50);
  border-radius: 12px; padding: 16px; margin-bottom: 12px;
}
.preview-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.preview-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 8px; }
.preview-stat-item { padding: 10px; background: white; border-radius: 10px; border: 1px solid var(--color-border-light, #e2e8f0); }
</style>

<template>
  <div class="pd-col-title"><FontAwesomeIcon icon="edit" aria-hidden="true" /> 产品信息</div>
  <div class="pd-col-scroll">
    <ProductBasicForm :factory-options="factoryOptions" @open-image="(src) => emit('open-image', src)" />
    <ProductBatchImport />
  </div>
</template>

<script setup lang="ts">
import ProductBasicForm from './ProductBasicForm.vue'
import ProductBatchImport from './ProductBatchImport.vue'

defineProps<{
  factoryOptions: readonly string[]
}>()

const emit = defineEmits<{
  'open-image': [src: string]
}>()
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
</style>

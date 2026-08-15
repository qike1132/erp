<template>
  <UiDialog v-model:open="open" title="库存不足提示" max-width-class="max-w-[480px]">
    <div class="so-stock-warning">
      <div class="so-stock-warning-icon">
        <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
      </div>
      <p class="so-stock-warning-title">该国家定制库存不足以完成出库</p>
      <div class="so-stock-warning-detail">
        <div class="so-stock-warning-row">
          <span class="so-stock-warning-label">产品</span>
          <span class="so-stock-warning-value">{{ data.productName }}</span>
        </div>
        <div class="so-stock-warning-row">
          <span class="so-stock-warning-label">国家</span>
          <span class="so-stock-warning-value">{{ data.country }}</span>
        </div>
        <div class="so-stock-warning-row">
          <span class="so-stock-warning-label">该国家可用库存</span>
          <span class="so-stock-warning-value so-stock-warning-num">{{ data.availableStock }}</span>
        </div>
        <div class="so-stock-warning-row">
          <span class="so-stock-warning-label">出库需求数量</span>
          <span class="so-stock-warning-value so-stock-warning-num so-stock-warning-demand">{{ data.demandQty }}</span>
        </div>
      </div>
    </div>
    <template #footer>
      <UiButton variant="primary" @click="open = false">知道了</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import UiButton from '@/components/ui/UiButton.vue'
import UiDialog from '@/components/ui/UiDialog.vue'

defineProps<{
  data: { productName: string; country: string; availableStock: number; demandQty: number }
}>()

const open = defineModel<boolean>('open', { default: false })
</script>

<style scoped>
.so-stock-warning { text-align: center; padding: 8px 0; }
.so-stock-warning-icon { font-size: 40px; color: var(--color-warning-500, #f59e0b); margin-bottom: 12px; }
.so-stock-warning-title { font-size: 15px; font-weight: 600; color: var(--color-text-primary); margin: 0 0 16px; }
.so-stock-warning-detail { display: inline-block; text-align: left; background: var(--color-bg-secondary, #f8fafc); border-radius: 10px; padding: 12px 20px; }
.so-stock-warning-row { display: flex; justify-content: space-between; gap: 24px; padding: 6px 0; font-size: 13px; }
.so-stock-warning-row + .so-stock-warning-row { border-top: 1px solid var(--color-border-light, #f1f5f9); }
.so-stock-warning-label { color: var(--color-text-secondary); }
.so-stock-warning-value { font-weight: 500; color: var(--color-text-primary); }
.so-stock-warning-num { font-variant-numeric: tabular-nums; }
.so-stock-warning-demand { color: var(--color-danger-500, #ef4444); }
</style>

<template>
  <UiDialog v-model:open="open" title="出货详情" max-width-class="max-w-[500px]">
    <div v-if="data" class="so-detail-dialog">
      <div class="so-detail-grid">
        <div class="so-detail-cell">
          <span class="so-detail-label">出货时间</span>
          <span class="so-detail-value">{{ data.stockout_date || '-' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">客户</span>
          <span class="so-detail-value">{{ data.customer || '-' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">产品</span>
          <span class="so-detail-value">{{ data.product_name || data.product?.name || '-' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">69码</span>
          <span class="so-detail-value so-detail-mono">{{ data.barcode || data.product?.barcode || '-' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">数量</span>
          <span class="so-detail-value"><strong>{{ data.quantity }}</strong></span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">抵扣备货</span>
          <span class="so-detail-value">{{ (data.deduct_quantity ?? 0) > 0 ? `抵扣: ${data.deduct_quantity}` : '否' }}</span>
        </div>
      </div>
      <div v-if="data.note" class="so-detail-note">
        <span class="so-detail-label">备注</span>
        <span class="so-detail-value">{{ data.note }}</span>
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="open = false">关闭</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import UiDialog from '@/components/ui/UiDialog.vue'
import UiButton from '@/components/ui/UiButton.vue'

interface StockoutRecord {
  id?: number
  stockout_date?: string
  product?: { id?: number; name?: string; image?: string; barcode?: string }
  product_name?: string
  barcode?: string
  customer?: string
  quantity?: number
  deduct_quantity?: number
  note?: string
}

defineProps<{
  data: StockoutRecord | null
}>()

const open = defineModel<boolean>('open', { default: false })
</script>

<style scoped>
.so-detail-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.so-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  overflow: hidden;
}
.so-detail-cell {
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.so-detail-cell:nth-child(odd) {
  border-right: 1px solid var(--color-border-light, #e2e8f0);
}
.so-detail-cell:nth-last-child(-n+2) {
  border-bottom: none;
}
.so-detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.so-detail-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}
.so-detail-mono {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  letter-spacing: 0.02em;
}
.so-detail-note {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 16px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
}
@media (max-width: 767.98px) {
  .so-detail-grid { grid-template-columns: 1fr; }
  .so-detail-cell:nth-child(odd) { border-right: none; }
}
</style>
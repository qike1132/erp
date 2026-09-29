<template>
  <div class="sp-modal-main">
    <div v-if="items" class="sp-plan-list-header">
      <span class="sp-plan-list-header-name">产品</span>
      <div class="sp-plan-list-header-qtys">
        <span>计划</span>
        <span>已生产</span>
        <span>待生产</span>
      </div>
    </div>
    <div v-if="items" class="sp-modal-main-list">
      <VirtualList
        :items="items"
        :item-height="54"
        :container-height="420"
        :item-key="(p) => p.detail_id"
      >
        <template #default="{ item: p }">
          <div class="sp-plan-item" style="margin-bottom:0;">
            <div class="sp-plan-left">
              <span class="sp-plan-name">{{ p.product_name }}</span>
              <code class="sp-plan-barcode">{{ p.barcode }}</code>
            </div>
            <div class="sp-plan-middle">
              <div class="sp-plan-qtys">
                <span class="sp-plan-qty-value">{{ p.quantity }}</span>
                <span class="sp-plan-qty-value sp-qty-green">{{ p.produced_qty }}</span>
                <span class="sp-plan-qty-value" :class="p.remaining_qty > 0 ? 'sp-qty-orange' : ''">{{ p.remaining_qty }}</span>
              </div>
            </div>
          </div>
        </template>
      </VirtualList>
    </div>
    <div v-else class="sp-modal-empty">
      <FontAwesomeIcon icon="hand-pointer" aria-hidden="true" />请从左侧选择客户
    </div>
  </div>
</template>

<script setup lang="ts">
import VirtualList from '@/components/ui/VirtualList.vue';
import type { Plan } from './types';

defineProps<{ items: Plan[] | null }>();
</script>

<style scoped>
.sp-modal-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.sp-modal-main-list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.sp-plan-item {
  padding: 8px 16px;
  margin-bottom: 6px;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  background: white;
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}
.sp-plan-item:hover {
  border-color: var(--color-primary-500);
  background: var(--color-primary-50);
  box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}
.sp-plan-left {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.sp-plan-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.sp-plan-barcode {
  font-size: 12px;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}
.sp-plan-middle {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-left: auto;
}
.sp-plan-list-header {
  display: flex;
  align-items: center;
  padding: 0 16px 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--color-border-light);
  margin-bottom: 6px;
}
.sp-plan-list-header-qtys {
  display: flex;
  gap: 20px;
  margin-left: auto;
}
.sp-plan-list-header-qtys span {
  min-width: 36px;
  text-align: right;
}
.sp-plan-list-header-name { min-width: 0; }
.sp-plan-qtys { display: flex; gap: 20px; }
.sp-plan-qtys .sp-plan-qty-value {
  min-width: 36px;
  text-align: right;
}
.sp-plan-qty-value {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-heading);
}
.sp-qty-green { color: var(--color-success-600); }
.sp-qty-orange { color: var(--color-warning-600); }
.sp-modal-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  color: var(--color-text-muted);
  font-size: 14px;
}
.sp-modal-empty i { font-size: 28px; opacity: 0.5; }
</style>
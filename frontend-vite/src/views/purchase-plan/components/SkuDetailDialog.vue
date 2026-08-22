<template>
  <Transition name="sp-modal">
    <div v-if="open" class="sp-modal-bg" @click.self="close">
      <div class="sp-sku-detail-modal">
        <div class="sp-sku-detail-header">
          <div>
            <div class="sp-sku-detail-title">{{ name }}</div>
            <div class="sp-sku-detail-sub">{{ barcode }}</div>
          </div>
          <button class="sp-modal-btn sp-modal-btn-close" aria-label="关闭" @click="close"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
        </div>
        <div class="sp-sku-detail-body">
          <div v-if="!dateDetail.length" class="sp-sku-detail-empty">该 SKU 本月暂无出货计划</div>
          <div v-else class="sp-sku-detail-list">
            <div class="sp-sku-detail-header-row">
              <span class="sp-sku-detail-header-label">日期</span>
              <span class="sp-sku-detail-header-label">数量</span>
            </div>
            <div v-for="item in dateDetail" :key="item.date" class="sp-sku-detail-row" :class="{ 'sp-sku-detail-shipped': item.status === 'completed' }">
              <span class="sp-sku-detail-date">{{ item.date }}</span>
              <span class="sp-sku-detail-qty">{{ item.qty }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import type { SkuDateItem } from './types';

const props = defineProps<{
  open: boolean;
  barcode: string;
  name: string;
  dateDetail: SkuDateItem[];
}>();

const emit = defineEmits<{
  'update:open': [value: boolean];
}>();

function close() {
  emit('update:open', false);
}
</script>

<style scoped>
.sp-modal-bg {
  position: fixed;
  inset: 0;
  z-index: 900;
  background: rgba(0,0,0,0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.sp-modal-btn {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.3s ease, color 0.3s ease, background 0.3s ease;
}

.sp-modal-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-sku-detail-modal {
  background: white;
  border-radius: var(--radius-modal, 28px);
  box-shadow: 0 12px 48px rgba(0,0,0,0.15);
  width: 90%;
  max-width: 640px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transform: translateZ(0);
  contain: layout style paint;
}

.sp-sku-detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-sku-detail-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-heading);
}

.sp-sku-detail-sub {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.sp-sku-detail-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}

.sp-sku-detail-empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: 40px 0;
  font-size: 14px;
}

.sp-sku-detail-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.sp-sku-detail-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  margin-bottom: 4px;
}

.sp-sku-detail-header-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.sp-sku-detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.sp-sku-detail-row:last-child {
  border-bottom: none;
}

.sp-sku-detail-shipped .sp-sku-detail-date {
  color: var(--color-success-600);
}

.sp-sku-detail-date {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-heading);
}

.sp-sku-detail-qty {
  font-size: 16px;
  font-weight: 800;
  color: var(--color-primary-700);
  font-variant-numeric: tabular-nums;
}
</style>

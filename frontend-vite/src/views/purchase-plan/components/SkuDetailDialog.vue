<template>
  <!-- 共享 UiDialog：Esc / 焦点陷阱 / 滚动锁内建；点遮罩空白不关闭（closeOnOverlayClick 默认 false） -->
  <UiDialog
    :open="open"
    max-width-class="max-w-[640px]"
    overlay-z-class="z-[var(--z-page-modal)]"
    content-z-class="z-[var(--z-page-modal)] sp-sku-detail-card"
    @update:open="emit('update:open', $event)"
  >
    <template #title>
      <div class="sp-sku-detail-title-wrap">
        <div class="sp-sku-detail-title">{{ name }}</div>
        <div class="sp-sku-detail-sub">{{ barcode }}</div>
      </div>
    </template>
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
  </UiDialog>
</template>

<script setup lang="ts">
import type { SkuDateItem } from './types';
import UiDialog from '@/components/ui/UiDialog.vue';

defineProps<{
  open: boolean;
  barcode: string;
  name: string;
  dateDetail: SkuDateItem[];
}>();

const emit = defineEmits<{
  'update:open': [value: boolean];
}>();
</script>

<style scoped>
/* 外壳（遮罩 / 卡片 / 头部 / 关闭）由共享 UiDialog 提供 */
.sp-sku-detail-title-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
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

<!-- 卡片由 UiDialog 渲染并 portal 到 body，scoped 样式够不到 → 全局维持迁移前的圆角 / 最大高度 -->
<style>
.sp-sku-detail-card {
  border-radius: var(--radius-modal, 28px) !important;
  max-height: 80vh !important;
}
</style>

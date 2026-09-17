<template>
  <!-- 根元素即全局 .page-card-header：仍保持为 .page-card 的直接子元素，布局不变 -->
  <div class="page-card-header">
    <div class="mc-header-title">
      <h1>物料用量计算</h1>
      <p>选择产品 → 录入订单数量 → 自动汇总填充 / 面料 / 辅料用量</p>
    </div>
    <div class="mc-header-actions">
      <span class="mc-count-badge">已选 {{ selectedCount }} 个</span>
      <button
        class="mc-action-btn mc-action-btn-primary"
        :disabled="orderCount === 0"
        aria-label="批量录入"
        @click="emit('batch')"
      >
        <FontAwesomeIcon icon="layer-group" aria-hidden="true" />
        批量录入
      </button>
      <button
        class="mc-action-btn mc-action-btn-danger"
        :disabled="orderCount === 0"
        aria-label="清空"
        @click="emit('clear')"
      >
        <FontAwesomeIcon icon="eraser" aria-hidden="true" />
        清空
      </button>
      <span v-if="calcStatus" :class="['mc-status-badge', calculating ? 'calculating' : 'done']">
        {{ calcStatus }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
// 物料计算器头部：标题 + 副标题说明 + 右侧操作区（计数徽章 / 批量录入 / 清空 / 计算状态）。
// 从 MaterialCalculatorView.vue 抽出，纯粹为控制单 SFC 行数（门禁 ≤400 行），行为不变。
defineProps<{
  /** 已选产品数 */
  selectedCount: number
  /** 已录入订单条目数（为 0 时操作按钮禁用） */
  orderCount: number
  /** 计算状态文案：计算中… / N 种物料 / 空串（空串则不渲染徽章） */
  calcStatus: string
  calculating: boolean
}>()

const emit = defineEmits<{
  batch: []
  clear: []
}>()
</script>

<style scoped>
/* 卡片头部容器样式在全局 .page-card-header（src/styles/app.css），此处只收紧内边距 */
.page-card-header {
  padding: var(--sp-3) var(--sp-5);
}

.mc-header-title {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.mc-header-title h1 {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
  line-height: 1.4;
  letter-spacing: -0.01em;
  color: var(--color-text);
}
.mc-header-title p {
  margin: 0;
  font-size: var(--fs-cap);
  line-height: 1.5;
  color: var(--color-text-muted);
}

.mc-header-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-left: auto;
  flex-shrink: 0;
}

.mc-count-badge {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 var(--sp-3);
  border-radius: var(--r-sm);
  background: var(--color-primary-50);
  color: var(--color-primary-700);
  font-size: var(--fs-xs);
  font-weight: 600;
}

.mc-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 11px;
  border: var(--bw) solid var(--color-border);
  border-radius: var(--r-sm);
  background: #fff;
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}

/* FontAwesomeIcon 渲染的是 <svg>，不是 <i> —— 尺寸必须打在 svg 上才生效 */
.mc-action-btn :deep(svg) {
  width: 12px;
  height: 12px;
}

.mc-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.mc-action-btn-primary {
  color: var(--color-primary-700);
  border-color: var(--color-primary-200);
  background: var(--color-primary-50);
}
.mc-action-btn-primary:hover:not(:disabled) {
  border-color: var(--color-primary-400);
}

.mc-action-btn-danger {
  color: var(--color-danger-500);
}
.mc-action-btn-danger:hover:not(:disabled) {
  background: var(--color-danger-50);
  border-color: var(--color-danger-200);
}

.mc-status-badge {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 var(--sp-3);
  border-radius: var(--r-sm);
  font-size: var(--fs-xs);
  font-weight: 600;
}
.mc-status-badge.calculating {
  background: var(--color-warning-50);
  color: var(--color-warning-800);
}
.mc-status-badge.done {
  background: var(--color-success-50);
  color: var(--color-success-700);
}
</style>

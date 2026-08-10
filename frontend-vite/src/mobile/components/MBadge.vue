<template>
  <span :class="['m-badge', variant, { dot, interactive }]" @click="interactive && $emit('click')">
    <span v-if="dot" class="m-badge-dot" />
    <span class="m-badge-text"><slot /></span>
  </span>
</template>

<script setup lang="ts">
defineProps<{
  variant?: 'success' | 'warning' | 'error' | 'info' | 'neutral'
  dot?: boolean
  interactive?: boolean
}>()
defineEmits<{ (e: 'click'): void }>()
</script>

<style scoped>
.m-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: var(--m-radius-chip);
  font-size: var(--m-font-label-sm);
  font-weight: var(--m-font-weight-medium);
  line-height: 1.4;
  white-space: nowrap;
  transition: opacity 0.15s var(--m-ease-smooth);
}

.m-badge.interactive {
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.m-badge.interactive:active {
  opacity: 0.7;
}

/* Success */
.m-badge.success {
  background: var(--m-success-light);
  color: var(--m-success-dark);
}
/* Warning */
.m-badge.warning {
  background: var(--m-warning-light);
  color: var(--m-warning-dark);
}
/* Error */
.m-badge.error {
  background: var(--m-error-light);
  color: var(--m-error-dark);
}
/* Info */
.m-badge.info {
  background: var(--m-info-light);
  color: var(--m-info);
}
/* Neutral */
.m-badge.neutral {
  background: #F5F5F5;
  color: var(--m-text-secondary);
}

.m-badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  flex-shrink: 0;
}
</style>

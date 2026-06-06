<template>
  <div class="m-empty">
    <div class="m-empty-icon">
      <slot name="icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="40" height="40">
          <circle cx="12" cy="12" r="10" />
          <line x1="8" y1="15" x2="16" y2="15" />
          <line x1="9" y1="9" x2="9.01" y2="9" />
          <line x1="15" y1="9" x2="15.01" y2="9" />
        </svg>
      </slot>
    </div>
    <div class="m-empty-title">{{ title }}</div>
    <div v-if="subtitle" class="m-empty-subtitle">{{ subtitle }}</div>
    <slot name="action" />
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<style scoped>
.m-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px var(--m-gap-lg);
  text-align: center;
}

.m-empty-icon {
  color: var(--m-text-tertiary);
  margin-bottom: 12px;
}

.m-empty-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--m-text-primary);
}

.m-empty-subtitle {
  font-size: 14px;
  color: var(--m-text-secondary);
  margin-top: 4px;
  max-width: 280px;
}
</style>

<template>
  <div class="m-list">
    <div v-if="header" class="m-list-header">{{ header }}</div>
    <slot />
  </div>
</template>

<script setup lang="ts">
defineProps<{ header?: string }>()
</script>

<style scoped>
.m-list {
  background: var(--m-bg-card);
  border-radius: var(--m-radius-md);
  box-shadow: var(--m-shadow-card);
  overflow: hidden;
}

.m-list-header {
  padding: var(--m-gap-md) var(--m-gap-md) var(--m-gap-xs);
  font-size: 13px;
  font-weight: 600;
  color: var(--m-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
</style>

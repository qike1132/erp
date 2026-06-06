<template>
  <div :class="['m-spinner', size]">
    <div class="m-spinner-ring" />
  </div>
</template>

<script setup lang="ts">
defineProps<{ size?: 'sm' | 'md' | 'lg' }>()
</script>

<style scoped>
.m-spinner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.m-spinner.sm { width: 20px; height: 20px; }
.m-spinner.md { width: 32px; height: 32px; }
.m-spinner.lg { width: 48px; height: 48px; }

.m-spinner-ring {
  width: 100%;
  height: 100%;
  border: 2.5px solid rgba(0, 0, 0, 0.06);
  border-top-color: var(--m-accent-amber);
  border-radius: 50%;
  animation: m-spin 0.7s linear infinite;
}

@keyframes m-spin {
  to { transform: rotate(360deg); }
}
</style>

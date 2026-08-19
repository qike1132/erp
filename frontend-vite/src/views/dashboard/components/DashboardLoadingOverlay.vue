<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-surface/60 backdrop-blur-sm">
    <div class="flex flex-col items-center gap-3">
      <div class="w-10 h-10 rounded-[var(--radius-md)] bg-ocean-light flex items-center justify-center animate-pulse">
        <UiSpinner />
      </div>
      <span class="text-sm text-text-secondary font-medium">数据加载中...</span>
    </div>
  </div>
</template>

<script setup lang="ts">
</script>
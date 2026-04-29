<template>
  <div class="text-center py-12 text-text-muted">
    <i :class="['text-5xl mb-3 opacity-30 block', icon]" />
    <p class="text-sm m-0">
      <slot>{{ text }}</slot>
    </p>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    icon?: string
    text?: string
  }>(),
  {
    icon: 'fas fa-inbox',
    text: '暂无数据',
  },
)
</script>

<template>
  <div :class="['m-card', { interactive: clickable, padded }]" @click="clickable && $emit('click')">
    <div v-if="$slots.header" class="m-card-header">
      <slot name="header" />
    </div>
    <slot />
    <div v-if="$slots.footer" class="m-card-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  clickable?: boolean
  padded?: boolean
}>()
defineEmits<{ (e: 'click'): void }>()
</script>

<style scoped>
.m-card {
  background: var(--m-bg-card);
  border-radius: var(--m-radius-md);
  box-shadow: var(--m-shadow-card);
  overflow: hidden;
}

.m-card.interactive {
  cursor: pointer;
  transition: transform 0.2s var(--m-ease-smooth), box-shadow 0.2s var(--m-ease-smooth);
  -webkit-tap-highlight-color: transparent;
}

.m-card.interactive:active {
  transform: scale(0.97);
  box-shadow: var(--m-shadow-card-hover);
}

.m-card.padded {
  padding: var(--m-gap-md);
}

.m-card-header {
  padding: var(--m-gap-md) var(--m-gap-md) var(--m-gap-xs);
}

.m-card-footer {
  padding: var(--m-gap-xs) var(--m-gap-md) var(--m-gap-md);
  border-top: 0.5px solid rgba(0, 0, 0, 0.06);
}
</style>

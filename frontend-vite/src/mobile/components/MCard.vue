<template>
  <!-- 可点击卡片补键盘可达（A-M39） -->
  <div
    :class="['m-card', { interactive: clickable, padded }]"
    :role="clickable ? 'button' : undefined"
    :tabindex="clickable ? 0 : undefined"
    @click="clickable && $emit('click')"
    @keydown="onKeydown"
  >
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
const props = defineProps<{
  clickable?: boolean
  padded?: boolean
}>()
defineEmits<{ (e: 'click'): void }>()

/** Enter / Space 等价于点击（A-M39）：否则卡片在键盘与读屏下完全不可操作 */
function onKeydown(e: KeyboardEvent) {
  if (!props.clickable) return
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    ;(e.currentTarget as HTMLElement).click()
  }
}
</script>

<style scoped>
.m-card {
  background: var(--m-bg-card);
  border-radius: var(--m-radius-md);
  box-shadow: var(--m-shadow-card);
  overflow: hidden;
}

.m-card.interactive:focus-visible {
  outline: 2px solid var(--m-accent, #2563eb);
  outline-offset: 2px;
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

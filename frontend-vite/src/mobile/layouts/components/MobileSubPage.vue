<template>
  <Transition name="m-subpage" @after-leave="$emit('closed')">
    <div v-if="visible" class="m-subpage">
      <slot />
    </div>
  </Transition>
</template>

<script setup lang="ts">
defineProps<{ visible: boolean }>()
defineEmits<{ (e: 'closed'): void }>()
</script>

<style scoped>
.m-subpage {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: var(--m-bg-deep);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.m-subpage-enter-active {
  transition: transform 0.35s var(--m-ease-smooth);
}

.m-subpage-leave-active {
  transition: transform 0.3s var(--m-ease-smooth);
}

.m-subpage-enter-from {
  transform: translateX(100%);
}

.m-subpage-leave-to {
  transform: translateX(100%);
}
</style>

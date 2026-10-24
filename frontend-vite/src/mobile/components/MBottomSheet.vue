<template>
  <Teleport to="body">
    <Transition name="m-sheet">
      <div v-if="visible" class="m-sheet-overlay" @click="handleOverlayClick">
        <div class="m-sheet-container" @click.stop>
          <div class="m-sheet-handle" />
          <div v-if="title" class="m-sheet-title">{{ title }}</div>
          <div class="m-sheet-body">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  title?: string
  dismissible?: boolean
}>()
const props = defineProps<{
  visible: boolean
  title?: string
  dismissible?: boolean
}>()
const emit = defineEmits<{ (e: 'update:visible', v: boolean): void; (e: 'close'): void }>()

function handleOverlayClick() {
  // F3-07（2026-10-24 审计）：dismissible=false 时 overlay 点击不关——原先声明
  // 了语义没实现（防误关表单抽屉的场景会静默失效）。
  if (props.dismissible === false) return
  emit('update:visible', false)
  emit('close')
}
</script>

<style scoped>
.m-sheet-overlay {
  position: fixed;
  inset: 0;
  z-index: 300;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: flex-end;
}

.m-sheet-container {
  width: 100%;
  max-height: 85vh;
  background: var(--m-bg-surface);
  border-radius: 20px 20px 0 0;
  padding: 8px var(--m-gap-md) calc(var(--m-gap-md) + var(--m-safe-bottom));
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.m-sheet-handle {
  width: 36px;
  height: 5px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.12);
  margin: 0 auto 12px;
}

.m-sheet-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--m-text-primary);
  text-align: center;
  margin-bottom: 12px;
}

.m-sheet-enter-active .m-sheet-container { transition: transform 0.35s var(--m-ease-spring); }
.m-sheet-enter-active { transition: opacity 0.25s var(--m-ease-smooth); }
.m-sheet-leave-active .m-sheet-container { transition: transform 0.25s var(--m-ease-smooth); }
.m-sheet-leave-active { transition: opacity 0.2s var(--m-ease-smooth); }
.m-sheet-enter-from { opacity: 0; }
.m-sheet-enter-from .m-sheet-container { transform: translateY(100%); }
.m-sheet-leave-to { opacity: 0; }
.m-sheet-leave-to .m-sheet-container { transform: translateY(100%); }
</style>

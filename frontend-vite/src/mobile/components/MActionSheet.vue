<template>
  <Teleport to="body">
    <Transition name="m-action">
      <div v-if="visible" class="m-action-overlay" @click="handleCancel">
        <div class="m-action-container" @click.stop>
          <div class="m-action-group">
            <button
              v-for="action in actions"
              :key="action.name"
              :class="['m-action-btn', action.destructive ? 'destructive' : '']"
              @click="handleAction(action)"
            >
              {{ action.label }}
            </button>
          </div>
          <button class="m-action-cancel" aria-label="取消" @click="handleCancel">取消</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
interface ActionItem {
  name: string
  label: string
  destructive?: boolean
}

defineProps<{
  visible: boolean
  actions: ActionItem[]
}>()
const emit = defineEmits<{
  (e: 'select', name: string): void
  (e: 'cancel'): void
  (e: 'update:visible', v: boolean): void
}>()

function handleAction(action: ActionItem) {
  emit('select', action.name)
  emit('update:visible', false)
}

function handleCancel() {
  emit('cancel')
  emit('update:visible', false)
}
</script>

<style scoped>
.m-action-overlay {
  position: fixed;
  inset: 0;
  z-index: 300;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: flex-end;
  padding: 0 8px calc(8px + var(--m-safe-bottom));
}

.m-action-container {
  width: 100%;
}

.m-action-group {
  background: var(--m-bg-surface);
  border-radius: 14px;
  overflow: hidden;
  margin-bottom: 8px;
}

.m-action-btn {
  width: 100%;
  padding: 16px;
  border: none;
  background: none;
  font-size: 20px;
  font-weight: 400;
  color: var(--m-accent);
  cursor: pointer;
  text-align: center;
  font-family: inherit;
  border-bottom: 0.5px solid rgba(0, 0, 0, 0.08);
  -webkit-tap-highlight-color: transparent;
}

.m-action-btn:last-child {
  border-bottom: none;
}

.m-action-btn.destructive {
  color: var(--m-accent-rose);
}

.m-action-btn:active {
  background: rgba(0, 0, 0, 0.04);
}

.m-action-cancel {
  width: 100%;
  padding: 16px;
  border: none;
  background: var(--m-bg-surface);
  border-radius: 14px;
  font-size: 20px;
  font-weight: 600;
  color: var(--m-accent);
  cursor: pointer;
  font-family: inherit;
  -webkit-tap-highlight-color: transparent;
}

.m-action-cancel:active {
  background: rgba(0, 0, 0, 0.04);
}

.m-action-enter-active { transition: opacity 0.2s var(--m-ease-smooth); }
.m-action-leave-active { transition: opacity 0.15s var(--m-ease-smooth); }
.m-action-enter-from, .m-action-leave-to { opacity: 0; }
</style>

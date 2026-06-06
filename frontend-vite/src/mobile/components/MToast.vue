<template>
  <Teleport to="body">
    <Transition name="m-toast">
      <div v-if="visible" :class="['m-toast', type]" @click="dismiss">
        <div class="m-toast-icon">
          <svg v-if="type === 'success'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <svg v-else-if="type === 'error'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
            <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
            <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
        </div>
        <span class="m-toast-msg">{{ message }}</span>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  message: string
  type?: 'success' | 'error' | 'info'
  duration?: number
}>()

const visible = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

function show() {
  visible.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(dismiss, props.duration ?? 2500)
}

function dismiss() {
  visible.value = false
  if (timer) { clearTimeout(timer); timer = null }
}

watch(() => props.message, (v) => { if (v) show() }, { immediate: true })

defineExpose({ show, dismiss })
</script>

<style scoped>
.m-toast {
  position: fixed;
  top: calc(var(--m-safe-top) + 12px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border-radius: 14px;
  background: rgba(30, 30, 30, 0.92);
  backdrop-filter: blur(12px);
  color: white;
  font-size: 14px;
  font-weight: 500;
  max-width: 90vw;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.m-toast.success { background: rgba(48, 209, 88, 0.92); }
.m-toast.error { background: rgba(255, 59, 48, 0.92); }
.m-toast.info { background: rgba(30, 30, 30, 0.92); }

.m-toast-enter-active { transition: opacity 0.25s var(--m-ease-smooth), transform 0.25s var(--m-ease-spring); }
.m-toast-leave-active { transition: opacity 0.2s var(--m-ease-smooth), transform 0.2s var(--m-ease-smooth); }
.m-toast-enter-from { opacity: 0; transform: translateX(-50%) translateY(-20px); }
.m-toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(-10px); }
</style>

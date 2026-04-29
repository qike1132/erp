<template>
  <Teleport to="body">
    <Transition name="toast">
      <div
        v-if="visible"
        :class="toastClasses"
        class="fixed top-5 right-5 px-5 py-3 rounded-lg text-white text-sm font-medium z-[99999] flex items-center gap-2 shadow-md"
      >
        <i :class="iconClass" />
        {{ message }}
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    visible: boolean
    message: string
    type?: 'success' | 'error' | 'warning' | 'info'
  }>(),
  {
    type: 'info',
  },
)

const typeClasses: Record<string, string> = {
  success: 'bg-success-500',
  error: 'bg-danger-500',
  warning: 'bg-warning-500',
  info: 'bg-primary-500',
}

const icons: Record<string, string> = {
  success: 'fas fa-check-circle',
  error: 'fas fa-times-circle',
  warning: 'fas fa-exclamation-circle',
  info: 'fas fa-info-circle',
}

const toastClasses = computed(() => typeClasses[props.type])
const iconClass = computed(() => icons[props.type])
</script>

<style scoped>
.toast-enter-active {
  transition: all 0.3s ease;
}
.toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from {
  transform: translateX(100%);
  opacity: 0;
}
.toast-leave-to {
  opacity: 0;
}
</style>

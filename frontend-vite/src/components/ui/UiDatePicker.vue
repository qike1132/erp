<template>
  <div class="date-picker-wrap">
    <input
      ref="inputRef"
      :id="inputId"
      type="date"
      :value="modelValue"
      :disabled="disabled"
      :aria-label="label || '选择日期'"
      class="date-input"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @click="openPicker"
    />
    <i class="fas fa-calendar-alt date-icon" @click="openPicker" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

let _idCounter = 0

const props = withDefaults(
  defineProps<{
    modelValue?: string
    disabled?: boolean
    label?: string
    placeholder?: string
    id?: string
  }>(),
  {},
)

defineEmits<{
  'update:modelValue': [value: string]
}>()

const inputId = computed(() => props.id || `ui-datepicker-${++_idCounter}`)

const inputRef = ref<HTMLInputElement | null>(null)

function openPicker() {
  if (props.disabled) return
  try {
    inputRef.value?.showPicker()
  } catch {
    // Fallback: focus the input if showPicker not supported
    inputRef.value?.focus()
  }
}
</script>

<style scoped>
.date-picker-wrap {
  position: relative;
  width: 100%;
}

.date-input {
  width: 100%;
  padding: 0.625rem 2.5rem 0.625rem 1rem;
  font-size: 0.9375rem;
  line-height: 1.5;
  color: var(--color-heading);
  background: white;
  border: 2px solid var(--color-ocean-light);
  border-radius: var(--radius-input);
  transition: all 0.3s ease;
  outline: none;
  min-height: 44px;
  box-sizing: border-box;
  font-family: inherit;
  cursor: pointer;
  /* Hide default calendar icon in Chrome/Edge */
  -webkit-appearance: none;
  appearance: none;
}

.date-input:focus {
  background: var(--color-surface-card);
  border-color: var(--color-ocean-deep);
  box-shadow: 0 0 0 0.2rem rgba(135, 206, 235, 0.25);
}

.date-input:not(:disabled):hover {
  border-color: var(--color-ocean-deep);
}

.date-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.date-icon {
  position: absolute;
  right: 0.875rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-ocean-text);
  font-size: 0.875rem;
  cursor: pointer;
}

/* Firefox date input fix */
.date-input::-moz-date-picker-indicator {
  opacity: 0;
  position: absolute;
  right: 0.5rem;
  width: 24px;
  height: 24px;
  cursor: pointer;
}
</style>

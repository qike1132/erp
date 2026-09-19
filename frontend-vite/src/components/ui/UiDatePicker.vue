<template>
  <div class="date-picker-wrap">
    <input
      :id="inputId"
      ref="inputRef"
      type="date"
      :value="modelValue"
      :disabled="disabled"
      :name="name"
      :autocomplete="autocomplete"
      :aria-label="label || '选择日期'"
      :aria-required="required || undefined"
      class="date-input"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @click="openPicker"
    />
    <button type="button" class="date-icon" aria-label="选择日期" @click="openPicker"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /></button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

let _idCounter = 0

/**
 * 回退 id 在 setup 阶段一次性求值。
 * 不能放进 computed getter：那样每次重算都会自增，id 会变，
 * 任何 label[for] / aria-describedby 关联都会在重渲染后失配。
 */
const fallbackId = `ui-datepicker-${++_idCounter}`

const props = withDefaults(
  defineProps<{
    modelValue?: string
    disabled?: boolean
    label?: string
    placeholder?: string
    id?: string
    name?: string
    autocomplete?: string
    /** 必填项：向辅助技术暴露 aria-required */
    required?: boolean
  }>(),
  {},
)

defineEmits<{
  'update:modelValue': [value: string]
}>()

const inputId = computed(() => props.id || fallbackId)

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
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  min-height: 44px;
  box-sizing: border-box;
  font-family: inherit;
  cursor: pointer;
  /* Hide default calendar icon in Chrome/Edge */
  -webkit-appearance: none;
  appearance: none;
}
.date-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }

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
  right: 0.5rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-ocean-text);
  font-size: 0.875rem;
  cursor: pointer;
  background: none;
  border: none;
  /* 命中区放大到 32×32：原实现仅 18×14，远低于最小可点击尺寸 */
  min-width: 32px;
  min-height: 32px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}
.date-icon:hover {
  background: var(--color-primary-50);
}
.date-icon:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}

/* 隐藏 Chromium 的原生日历指示器，避免与自定义 .date-icon 叠成两个图标 */
.date-input::-webkit-calendar-picker-indicator {
  opacity: 0;
  position: absolute;
  right: 0;
  width: 40px;
  height: 100%;
  margin: 0;
  padding: 0;
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

<template>
  <div :class="['m-form-item', { error: !!error, disabled }]">
    <label v-if="label" :for="inputId" class="m-form-label">
      {{ label }}
      <span v-if="required" class="m-form-required">*</span>
    </label>

    <div class="m-form-control">
      <!-- Text Input -->
      <input
        v-if="type === 'text' || type === 'number' || type === 'tel' || type === 'email'"
        :id="inputId"
        :type="type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :readonly="readonly"
        :inputmode="inputMode"
        class="m-form-input"
        @input="onInput"
        @blur="$emit('blur')"
      />

      <!-- Textarea -->
      <textarea
        v-else-if="type === 'textarea'"
        :id="inputId"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :rows="rows"
        class="m-form-input m-form-textarea"
        @input="onTextareaInput"
        @blur="$emit('blur')"
      />

      <!-- Select -->
      <button
        v-else-if="type === 'select'"
        :id="inputId"
        class="m-form-select"
        :disabled="disabled"
        @click="$emit('selectClick')"
      >
        <span :class="{ placeholder: !modelValue }">{{ modelValue || placeholder }}</span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
          <polyline points="6 9 12 15 18 9" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>

      <!-- Custom slot -->
      <slot v-else name="control" />
    </div>

    <p v-if="error" class="m-form-error">{{ error }}</p>
    <p v-if="hint && !error" class="m-form-hint">{{ hint }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  modelValue?: string | number
  label?: string
  type?: 'text' | 'number' | 'tel' | 'email' | 'textarea' | 'select' | 'custom'
  placeholder?: string
  error?: string
  hint?: string
  required?: boolean
  disabled?: boolean
  readonly?: boolean
  rows?: number
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: string): void
  (e: 'blur'): void
  (e: 'selectClick'): void
}>()

const inputId = computed(() => `m-input-${Math.random().toString(36).slice(2, 9)}`)
const inputMode = computed(() => {
  if (props.type === 'number') return 'decimal'
  if (props.type === 'tel') return 'tel'
  if (props.type === 'email') return 'email'
  return 'text'
})

function onInput(e: Event) {
  const val = (e.target as HTMLInputElement).value
  emit('update:modelValue', props.type === 'number' ? val.replace(/[^\d.-]/g, '') : val)
}

function onTextareaInput(e: Event) {
  const val = (e.target as HTMLTextAreaElement).value
  emit('update:modelValue', val)
}
</script>

<style scoped>
.m-form-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: var(--m-gap-md);
}

.m-form-item.disabled {
  opacity: 0.5;
  pointer-events: none;
}

.m-form-label {
  font-size: var(--m-font-label-sm);
  font-weight: var(--m-font-weight-medium);
  color: var(--m-text-secondary);
  line-height: 1.2;
}

.m-form-required {
  color: var(--m-error);
  margin-left: 2px;
}

.m-form-control {
  position: relative;
}

.m-form-input {
  width: 100%;
  padding: 12px 14px;
  font-size: var(--m-font-body-lg);
  font-family: inherit;
  color: var(--m-text-primary);
  background: var(--m-bg-surface);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: var(--m-radius-input);
  outline: none;
  transition: border-color 0.2s var(--m-ease-smooth), box-shadow 0.2s var(--m-ease-smooth);
  -webkit-appearance: none;
  appearance: none;
  box-sizing: border-box;
}

.m-form-input::placeholder {
  color: var(--m-text-tertiary);
}
.m-form-input:focus {
  border-color: var(--m-accent);
  box-shadow: 0 0 0 3px var(--m-accent-glow);
}

.m-form-item.error .m-form-input {
  border-color: var(--m-error);
}
.m-form-item.error .m-form-input:focus {
  box-shadow: 0 0 0 3px var(--m-error-glow);
}

.m-form-textarea {
  resize: vertical;
  min-height: 80px;
  line-height: 1.5;
}

.m-form-select {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  font-size: var(--m-font-body-lg);
  font-family: inherit;
  color: var(--m-text-primary);
  background: var(--m-bg-surface);
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: var(--m-radius-input);
  cursor: pointer;
  text-align: left;
  -webkit-tap-highlight-color: transparent;
}

.m-form-select .placeholder {
  color: var(--m-text-tertiary);
}

.m-form-select:active {
  background: var(--m-bg-grouped);
}

.m-form-error {
  font-size: var(--m-font-label-sm);
  color: var(--m-error);
  margin: 0;
}

.m-form-hint {
  font-size: var(--m-font-label-sm);
  color: var(--m-text-tertiary);
  margin: 0;
}
</style>

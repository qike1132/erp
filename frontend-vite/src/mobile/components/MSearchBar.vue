<template>
  <div class="m-search">
    <svg class="m-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
    <input
      ref="inputRef"
      :value="modelValue"
      type="search"
      :placeholder="placeholder"
      class="m-search-input"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @keydown.enter="$emit('search', modelValue)"
    />
    <button v-if="modelValue" class="m-search-clear" aria-label="操作按钮" @click="handleClear">
      <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
        <circle cx="12" cy="12" r="10" fill="currentColor" opacity="0.2" />
        <path d="M15 9l-6 6M9 9l6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  modelValue: string
  placeholder?: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'search', v: string): void
}>()

const inputRef = ref<HTMLInputElement>()

function handleClear() {
  emit('update:modelValue', '')
  inputRef.value?.focus()
}

defineExpose({ focus: () => inputRef.value?.focus() })
</script>

<style scoped>
.m-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  height: 36px;
  background: var(--m-bg-grouped);
  border-radius: 10px;
}

.m-search-icon {
  color: var(--m-text-tertiary);
  flex-shrink: 0;
}

.m-search-input {
  flex: 1;
  border: none;
  background: none;
  font-size: 15px;
  color: var(--m-text-primary);
  outline: none;
  font-family: inherit;
  min-width: 0;
}

.m-search-input::placeholder {
  color: var(--m-text-tertiary);
}

.m-search-input::-webkit-search-cancel-button {
  display: none;
}

.m-search-clear {
  border: none;
  background: none;
  color: var(--m-text-tertiary);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  -webkit-tap-highlight-color: transparent;
}
</style>

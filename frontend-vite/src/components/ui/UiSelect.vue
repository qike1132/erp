<template>
  <ComboboxRoot
    :model-value="modelValue"
    :open="isOpen"
    :ignore-filter="true"
    @update:model-value="onSelect"
    @update:open="onOpenChange"
  >
    <div class="ui-select-wrapper">
      <ComboboxAnchor>
        <ComboboxInput
          :value="searchQuery"
          :placeholder="placeholder"
          :disabled="disabled"
          :aria-label="label || placeholder"
          class="ui-select-input"
          @input="onInput"
          @focus="onFocus"
        />
        <ComboboxTrigger
          class="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted border-none bg-transparent cursor-pointer p-0"
          :disabled="disabled"
        >
          <i class="fas fa-chevron-down text-xs" />
        </ComboboxTrigger>
      </ComboboxAnchor>

      <ComboboxContent
        :class="[
          'ui-select-dropdown bg-white border border-border rounded-xl shadow-lg max-h-[240px] overflow-y-auto py-1',
          contentClass,
        ]"
        position="inline"
      >
        <ComboboxViewport>
          <ComboboxEmpty class="px-3 py-2 text-[13px] text-text-muted">
            {{ emptyText }}
          </ComboboxEmpty>
          <ComboboxItem
            v-for="item in filteredItems"
            :key="item.value"
            :value="item.value"
            class="px-3 py-2 text-[13px] text-text cursor-pointer rounded-md mx-1 outline-none data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-700 transition-colors flex items-center"
          >
            <ComboboxItemIndicator class="mr-1 text-primary-500">
              <i class="fas fa-check text-[10px]" />
            </ComboboxItemIndicator>
            <span>{{ item.label }}</span>
          </ComboboxItem>
        </ComboboxViewport>
      </ComboboxContent>
    </div>
  </ComboboxRoot>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  ComboboxRoot,
  ComboboxAnchor,
  ComboboxInput,
  ComboboxTrigger,
  ComboboxContent,
  ComboboxViewport,
  ComboboxItem,
  ComboboxItemIndicator,
  ComboboxEmpty,
} from 'reka-ui'

export interface SelectOption {
  value: string
  label: string
}

const props = withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    disabled?: boolean
    label?: string
    options?: SelectOption[]
    emptyText?: string
    contentClass?: string
  }>(),
  {
    options: () => [],
    emptyText: '无匹配项',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const searchQuery = ref('')
const isOpen = ref(false)

// Sync search query display with selected label
watch(
  () => props.modelValue,
  (val) => {
    const selected = props.options.find((o) => o.value === val)
    searchQuery.value = selected ? selected.label : ''
  },
  { immediate: true },
)

const filteredItems = computed(() => {
  if (!searchQuery.value) return props.options
  const q = searchQuery.value.toLowerCase()
  return props.options.filter((o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
})

function onInput(event: Event) {
  searchQuery.value = (event.target as HTMLInputElement).value
  if (!isOpen.value) isOpen.value = true
}

function onFocus() {
  searchQuery.value = ''
  isOpen.value = true
}

function onSelect(val: string) {
  emit('update:modelValue', val)
  const selected = props.options.find((o) => o.value === val)
  searchQuery.value = selected ? selected.label : val
  isOpen.value = false
}

function onOpenChange(val: boolean) {
  isOpen.value = val
  if (!val) {
    // Reset searchQuery to selected label when dropdown closes without selection
    const selected = props.options.find((o) => o.value === props.modelValue)
    searchQuery.value = selected ? selected.label : ''
  }
}
</script>

<style>
.ui-select-wrapper {
  position: relative;
}
.ui-select-input {
  width: 100%;
  padding: 0.625rem 2.5rem 0.625rem 1rem;
  font-size: 0.9375rem;
  line-height: 1.5;
  color: var(--color-heading);
  background: var(--color-slate-50);
  border: 2px solid var(--color-ocean-light);
  border-radius: var(--radius-input);
  transition: all 0.3s ease;
  outline: none;
  min-height: 44px;
  box-sizing: border-box;
  font-family: inherit;
  cursor: pointer;
}
.ui-select-input:focus {
  background: var(--color-surface-card);
  border-color: var(--color-ocean-deep);
  box-shadow: 0 0 0 0.2rem rgba(135, 206, 235, 0.25);
}
.ui-select-input:not(:disabled):hover {
  border-color: var(--color-ocean-deep);
}
.ui-select-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ui-select-dropdown {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  top: calc(100% + 4px);
  z-index: 9999;
  min-width: 100%;
  width: max-content;
  max-width: 320px;
}
</style>

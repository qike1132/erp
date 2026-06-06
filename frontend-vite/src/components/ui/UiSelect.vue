<template>
  <ComboboxRoot
    :model-value="modelValue"
    :ignore-filter="true"
    :open-on-click="true"
    :open-on-focus="true"
    @update:model-value="onSelect"
    @update:open="onOpenChange"
  >
    <div class="ui-select-wrapper">
      <ComboboxAnchor>
        <ComboboxInput
          :display-value="getDisplayValue"
          :placeholder="placeholder"
          :disabled="disabled"
          :aria-label="label || placeholder"
          :name="name"
          class="ui-select-input"
          @input="onInput"
        />
        <ComboboxTrigger
          class="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted border-none bg-transparent cursor-pointer p-0"
          :disabled="disabled"
          aria-label="选择选项"
        >
          <i class="fas fa-chevron-down text-xs" aria-hidden="true" />
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
            class="px-3 py-2 text-[13px] text-text cursor-pointer rounded-md mx-1 outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 data-[highlighted]:bg-primary-50 data-[highlighted]:text-primary-700 transition-colors flex items-center"
          >
            <ComboboxItemIndicator class="mr-1 text-primary-500">
              <i class="fas fa-check text-[10px]" aria-hidden="true" />
            </ComboboxItemIndicator>
            <span>{{ item.label }}</span>
          </ComboboxItem>
        </ComboboxViewport>
      </ComboboxContent>
    </div>
  </ComboboxRoot>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
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
    name?: string
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

const filteredItems = computed(() => {
  if (!searchQuery.value) return props.options
  const q = searchQuery.value.toLowerCase()
  return props.options.filter((o) => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
})

function getDisplayValue(val: unknown): string {
  if (val == null || val === '') return ''
  const selected = props.options.find((o) => o.value === val)
  return selected ? selected.label : String(val)
}

function onInput(event: InputEvent) {
  searchQuery.value = (event.target as HTMLInputElement).value
}

function onSelect(val: string) {
  emit('update:modelValue', val)
  const selected = props.options.find((o) => o.value === val)
  searchQuery.value = selected ? selected.label : val
}

function onOpenChange(open: boolean) {
  if (open) {
    searchQuery.value = ''
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
  background: white;
  border: 2px solid var(--color-ocean-light);
  border-radius: var(--radius-input);
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  min-height: 44px;
  box-sizing: border-box;
  font-family: inherit;
  cursor: pointer;
}
.ui-select-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.ui-select-input:focus {
  background: var(--color-surface-card);
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

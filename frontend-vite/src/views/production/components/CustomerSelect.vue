<template>
  <div class="pr-customer-select">
    <UiSelect
      :id="id"
      :model-value="modelValue == null ? '' : String(modelValue)"
      :options="selectOptions"
      :placeholder="placeholder"
      label="客户"
      @update:model-value="onSelect"
      @keydown.esc.stop
    />
    <button
      v-if="modelValue != null"
      type="button"
      class="pr-customer-clear"
      aria-label="清除客户"
      @click="emit('update:modelValue', null)"
    >
      ×
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import UiSelect from '@/components/ui/UiSelect.vue'

interface CustomerOption {
  id: number
  name: string
}

const props = withDefaults(defineProps<{
  modelValue: number | null
  options: CustomerOption[]
  placeholder?: string
  id?: string
}>(), {
  placeholder: '客户（选填）',
  id: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: number | null]
}>()

const selectOptions = computed(() => props.options.map((c) => ({
  value: String(c.id),
  label: c.name,
})))

function onSelect(value: string) {
  emit('update:modelValue', value ? Number(value) : null)
}
</script>

<style scoped>
.pr-customer-select {
  position: relative;
  width: 220px;
}

.pr-customer-clear {
  position: absolute;
  right: 30px;
  top: 50%;
  transform: translateY(-50%);
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  background: var(--color-border-light);
  color: var(--color-text-muted);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}

.pr-customer-clear:hover {
  background: var(--color-border);
  color: var(--color-text);
}

@media (max-width: 1100px) {
  .pr-customer-select {
    width: 100%;
  }
}
</style>

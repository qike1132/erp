<template>
  <input
    :id="inputId"
    :type="type"
    :value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :name="name"
    :autocomplete="autocomplete"
    :aria-label="label || placeholder"
    class="w-full py-2.5 px-4 border-2 border-ocean-light rounded-[var(--radius-input)] text-sm text-text bg-slate-50 transition-colors transition-shadow duration-300 focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:bg-white focus:border-ocean-deep focus:shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)] placeholder:text-text-muted disabled:opacity-50 disabled:cursor-not-allowed"
    @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'

let _idCounter = 0

const props = withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    type?: 'text' | 'password' | 'email' | 'number' | 'tel' | 'url'
    disabled?: boolean
    label?: string
    id?: string
    name?: string
    autocomplete?: string
  }>(),
  {
    type: 'text',
  },
)

defineEmits<{
  'update:modelValue': [value: string]
}>()

const inputId = computed(() => props.id || `ui-input-${++_idCounter}`)
</script>

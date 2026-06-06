<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    :aria-label="ariaLabel"
    :name="name"
    :class="[
      'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2',
      modelValue ? 'bg-primary-500' : 'bg-gray-300',
      disabled ? 'opacity-50 cursor-not-allowed' : '',
    ]"
    @click="$emit('update:modelValue', !modelValue)"
  >
    <span
      :class="[
        'pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition-transform duration-200 ease-in-out',
        modelValue ? 'translate-x-4' : 'translate-x-0',
      ]"
    />
  </button>
</template>

<script setup lang="ts">
defineProps<{
  modelValue: boolean
  disabled?: boolean
  ariaLabel?: string
  name?: string
}>()

defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

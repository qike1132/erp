<template>
  <CheckboxRoot
    as="div"
    :model-value="checked"
    :disabled="disabled"
    :aria-label="ariaLabel"
    :name="name"
    :class="[
      'w-[18px] h-[18px] rounded border-2 flex items-center justify-center transition-colors duration-200 cursor-pointer flex-shrink-0',
      checked ? 'bg-primary-500 border-primary-500 text-white' : 'bg-white border-border hover:border-primary-500',
      disabled ? 'opacity-50 cursor-not-allowed' : '',
    ]"
    @update:model-value="($event: boolean | 'indeterminate') => $emit('update:checked', $event === true)"
  >
    <CheckboxIndicator class="flex items-center justify-center">
      <FontAwesomeIcon icon="check" class="text-xs" aria-hidden="true" />
    </CheckboxIndicator>
  </CheckboxRoot>
</template>

<script setup lang="ts">
import { CheckboxRoot, CheckboxIndicator } from 'reka-ui'

withDefaults(
  defineProps<{
    checked: boolean
    disabled?: boolean
    ariaLabel?: string
    name?: string
  }>(),
  {
    disabled: false,
    ariaLabel: undefined,
    name: undefined,
  },
)

defineEmits<{ 'update:checked': [value: boolean] }>()
</script>

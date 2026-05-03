<template>
  <CheckboxRoot
    as="div"
    :model-value="checked"
    :disabled="disabled"
    :class="[
      'w-[18px] h-[18px] rounded border-2 flex items-center justify-center transition-all duration-200 cursor-pointer flex-shrink-0',
      checked ? 'bg-primary-500 border-primary-500 text-white' : 'bg-white border-border hover:border-primary-500',
      disabled ? 'opacity-50 cursor-not-allowed' : '',
    ]"
    @update:model-value="($event: boolean | 'indeterminate') => $emit('update:checked', $event === true)"
  >
    <CheckboxIndicator class="flex items-center justify-center">
      <i class="fas fa-check text-xs" />
    </CheckboxIndicator>
  </CheckboxRoot>
</template>

<script setup lang="ts">
import { CheckboxRoot, CheckboxIndicator } from 'reka-ui'

withDefaults(
  defineProps<{
    checked: boolean
    disabled?: boolean
  }>(),
  {
    disabled: false,
  },
)

defineEmits<{ 'update:checked': [value: boolean] }>()
</script>

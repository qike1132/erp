<template>
  <div class="w-full">
    <div v-if="label" class="block text-xs font-semibold text-text-secondary mb-1.5 uppercase tracking-wider">
      {{ label }}
    </div>
    <div class="relative flex items-center">
      <button
        type="button"
        :class="[
          'relative inline-flex items-center rounded-lg border border-border bg-white h-8 w-8 justify-center transition-all',
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-primary-500',
        ]"
        :disabled="disabled"
        @click="decrement"
      >
        <i class="fas fa-minus text-xs text-text-secondary" />
      </button>
      <input
        type="number"
        :value="modelValue"
        :min="min"
        :max="max"
        :step="step"
        :disabled="disabled"
        class="w-20 text-center py-1.5 border-y border-border text-[13px] text-text bg-white focus:outline-none focus:ring-2 focus:ring-primary-500/15 focus:border-primary-500 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
        @input="$emit('update:modelValue', Number(($event.target as HTMLInputElement).value))"
      />
      <button
        type="button"
        :class="[
          'relative inline-flex items-center rounded-lg border border-border bg-white h-8 w-8 justify-center transition-all',
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-primary-500',
        ]"
        :disabled="disabled"
        @click="increment"
      >
        <i class="fas fa-plus text-xs text-text-secondary" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: number
    min?: number
    max?: number
    step?: number
    disabled?: boolean
    label?: string
  }>(),
  { min: -Infinity, max: Infinity, step: 1 },
)

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

function decrement() {
  const next = props.modelValue - props.step
  emit('update:modelValue', Math.max(props.min, next))
}

function increment() {
  const next = props.modelValue + props.step
  emit('update:modelValue', Math.min(props.max, next))
}
</script>

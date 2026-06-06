<template>
  <div class="w-full">
    <label v-if="label" :for="inputId" class="block text-xs font-semibold text-text-secondary mb-1.5 uppercase tracking-wider">
      {{ label }}
    </label>
    <div class="relative flex items-center">
      <button
        type="button"
        :class="[
          'relative inline-flex items-center rounded-lg border border-border bg-white h-8 w-8 justify-center transition-colors',
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-primary-500',
        ]"
        :disabled="disabled"
        aria-label="减少"
        @click="decrement"
      >
        <i class="fas fa-minus text-xs text-text-secondary" aria-hidden="true" />
      </button>
      <input
        :id="inputId"
        type="number"
        inputmode="numeric"
        :value="modelValue"
        :min="min"
        :max="max"
        :step="step"
        :disabled="disabled"
        :name="name"
        :aria-label="label"
        class="w-20 text-center py-1.5 border-y border-border text-[13px] text-text bg-white tabular-nums focus:outline-none focus-visible:outline-2 focus-visible:outline-primary-500 focus-visible:outline-offset-2 focus:ring-2 focus:ring-primary-500/15 focus:border-primary-500 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
        @input="$emit('update:modelValue', Number(($event.target as HTMLInputElement).value))"
      />
      <button
        type="button"
        :class="[
          'relative inline-flex items-center rounded-lg border border-border bg-white h-8 w-8 justify-center transition-colors',
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:border-primary-500',
        ]"
        :disabled="disabled"
        aria-label="增加"
        @click="increment"
      >
        <i class="fas fa-plus text-xs text-text-secondary" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useId } from 'vue'

const inputId = useId()

const props = withDefaults(
  defineProps<{
    modelValue: number
    min?: number
    max?: number
    step?: number
    disabled?: boolean
    label?: string
    name?: string
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

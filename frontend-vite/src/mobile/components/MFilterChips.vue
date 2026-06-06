<template>
  <div class="m-filter-chips">
    <button
      v-for="chip in chips"
      :key="chip.value"
      :class="['m-chip', { active: modelValue === chip.value }]"
      @click="handleSelect(chip.value)"
    >
      {{ chip.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
interface ChipOption {
  label: string
  value: string | number
}

defineProps<{
  chips: ChipOption[]
  modelValue: string | number
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: string | number): void }>()

function handleSelect(value: string | number) {
  emit('update:modelValue', value)
}
</script>

<style scoped>
.m-filter-chips {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 2px 0;
  scrollbar-width: none;
  -ms-overflow-style: none;
  -webkit-overflow-scrolling: touch;
}

.m-filter-chips::-webkit-scrollbar {
  display: none;
}

.m-chip {
  flex-shrink: 0;
  padding: 6px 14px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  border-radius: 20px;
  background: var(--m-bg-surface);
  font-size: 13px;
  font-weight: 500;
  color: var(--m-text-secondary);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s var(--m-ease-smooth);
  -webkit-tap-highlight-color: transparent;
  white-space: nowrap;
}

.m-chip.active {
  background: var(--m-accent);
  color: white;
  border-color: var(--m-accent);
}

.m-chip:active {
  transform: scale(0.95);
}
</style>

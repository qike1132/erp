<template>
  <div class="m-progress">
    <div v-if="label" class="m-progress-label">
      <span>{{ label }}</span>
      <span v-if="showPercent" class="m-progress-pct">{{ pct }}%</span>
    </div>
    <div class="m-progress-track">
      <div
        class="m-progress-fill"
        :style="{
          width: pct + '%',
          background: color ?? defaultColor,
          transition: animated ? 'width 0.4s var(--m-ease-smooth)' : 'none',
        }"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  value: number
  max?: number
  label?: string
  showPercent?: boolean
  color?: string
  animated?: boolean
  status?: 'active' | 'success' | 'warning'
}>()

const pct = computed(() => {
  const m = props.max ?? 100
  return Math.min(100, Math.max(0, Math.round((props.value / m) * 100)))
})

const defaultColor = computed(() => {
  if (props.status === 'success') return 'var(--m-accent-emerald)'
  if (props.status === 'warning') return 'var(--m-accent-amber)'
  if (pct.value >= 100) return 'var(--m-accent-emerald)'
  return 'var(--m-accent-amber)'
})
</script>

<style scoped>
.m-progress {
  width: 100%;
}

.m-progress-label {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--m-text-secondary);
  margin-bottom: 4px;
}

.m-progress-pct {
  font-weight: 600;
  color: var(--m-text-primary);
  font-variant-numeric: tabular-nums;
}

.m-progress-track {
  height: 6px;
  background: rgba(0, 0, 0, 0.06);
  border-radius: 3px;
  overflow: hidden;
}

.m-progress-fill {
  height: 100%;
  border-radius: 3px;
}
</style>

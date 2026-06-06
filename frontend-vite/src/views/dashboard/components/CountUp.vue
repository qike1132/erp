<template>
  <span ref="displayRef">{{ displayValue }}</span>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'

const props = defineProps<{
  target: number
  duration?: number
}>()

const displayRef = ref<HTMLElement>()
const displayValue = ref(0)

let rafId: number | null = null

function animate(from: number, to: number, duration: number) {
  if (rafId) cancelAnimationFrame(rafId)

  const startTime = performance.now()

  function step(now: number) {
    const elapsed = now - startTime
    const progress = Math.min(elapsed / duration, 1)
    // easeOutQuart
    const eased = 1 - Math.pow(1 - progress, 4)
    displayValue.value = Math.round(from + (to - from) * eased)

    if (progress < 1) {
      rafId = requestAnimationFrame(step)
    }
  }

  rafId = requestAnimationFrame(step)
}

watch(() => props.target, (newVal, oldVal) => {
  animate(oldVal ?? 0, newVal, props.duration ?? 800)
})

onMounted(() => {
  animate(0, props.target, props.duration ?? 800)
})
</script>

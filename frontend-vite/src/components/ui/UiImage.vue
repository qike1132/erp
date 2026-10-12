<template>
  <img
    :src="src"
    :alt="alt ?? ''"
    :width="width"
    :height="height"
    :class="['object-cover rounded-lg', fitClass, className]"
    loading="lazy"
    @error="($event.target as HTMLImageElement).src = ''"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    src: string
    alt?: string
    fit?: 'contain' | 'cover' | 'fill' | 'none'
    className?: string
    width?: number | string
    height?: number | string
  }>(),
  { width: undefined, height: undefined, alt: undefined, fit: undefined, className: undefined },
)

const fitClass = computed(() => {
  switch (props.fit) {
    case 'contain':
      return 'object-contain'
    case 'fill':
      return 'object-fill'
    case 'none':
      return 'object-none'
    default:
      return 'object-cover'
  }
})
</script>

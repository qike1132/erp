<template>
  <img
    :src="src"
    :alt="alt"
    :class="['object-cover rounded-lg', fitClass, className]"
    loading="lazy"
    @error="($event.target as HTMLImageElement).src = ''"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  src: string
  alt?: string
  fit?: 'contain' | 'cover' | 'fill' | 'none'
  className?: string
}>()

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

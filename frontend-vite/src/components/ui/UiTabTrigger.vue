<template>
  <TabsTrigger
    :value="value"
    :class="[
      'flex-1 py-3 px-4 border-none cursor-pointer text-sm font-medium flex items-center justify-center gap-2 whitespace-nowrap transition-all duration-300',
      active
        ? 'bg-gradient-primary text-white shadow-md rounded-[var(--radius-nav-item)]'
        : 'bg-transparent text-text-secondary rounded-[var(--radius-nav-item)] hover:text-ocean-text hover:bg-ocean-light/40',
    ]"
  >
    <slot />
    <span
      v-if="badge !== undefined"
      :class="[
        'notification-badge',
        active ? 'notification-badge-active' : '',
      ]"
    >
      {{ badge }}
    </span>
  </TabsTrigger>
</template>

<script setup lang="ts">
import { TabsTrigger } from 'reka-ui'

defineProps<{
  value: string
  active?: boolean
  badge?: number
}>()
</script>

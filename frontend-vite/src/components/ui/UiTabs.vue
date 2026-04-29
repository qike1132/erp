<template>
  <TabsRoot :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)">
    <TabsList :class="['flex bg-surface-card rounded-[var(--radius-card)] p-1.5 shadow-sm gap-1 overflow-x-auto mb-5']">
      <slot />
    </TabsList>
  </TabsRoot>
</template>

<script setup lang="ts">
import { TabsRoot, TabsList } from 'reka-ui'

defineProps<{ modelValue: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

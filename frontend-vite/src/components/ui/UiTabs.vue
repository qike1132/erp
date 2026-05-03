<template>
  <TabsRoot :model-value="modelValue" @update:model-value="$emit('update:modelValue', $event)">
    <TabsList :class="['ui-tab-group']">
      <slot />
    </TabsList>
  </TabsRoot>
</template>

<script setup lang="ts">
import { TabsRoot, TabsList } from 'reka-ui'

defineProps<{ modelValue: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<style scoped>
.ui-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow-x: auto;
  margin-bottom: 20px;
}
</style>

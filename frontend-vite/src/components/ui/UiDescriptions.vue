<template>
  <div class="text-sm">
    <div v-for="row in rows" :key="row.label" class="flex py-2.5 border-b border-border-light last:border-b-0">
      <div class="w-1/3 text-text-secondary font-medium">
        {{ row.label }}
      </div>
      <div class="w-2/3 min-w-0 text-text">
        <slot :name="row.key" :value="row.value">
          {{ row.value }}
        </slot>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  rows: { label: string; key: string; value: unknown }[]
}>()
</script>

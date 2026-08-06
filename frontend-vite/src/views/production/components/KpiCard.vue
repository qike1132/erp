<template>
  <div :class="['pr-kpi-card', colorClass]">
    <div class="pr-kpi-icon-wrap"><i :class="iconClass" aria-hidden="true" /></div>
    <div class="pr-kpi-body">
      <span class="pr-kpi-label">{{ label }}</span>
      <span class="pr-kpi-value">{{ value }}<small v-if="unit" class="pr-kpi-unit">{{ unit }}</small></span>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  iconClass: string
  colorClass: string
  label: string
  value: string | number
  unit?: string
}>()
</script>

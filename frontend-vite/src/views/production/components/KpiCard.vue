<template>
  <div :class="['pr-kpi-card', colorClass]">
    <div class="pr-kpi-icon-wrap"><FontAwesomeIcon :icon="icon" aria-hidden="true" /></div>
    <div class="pr-kpi-body">
      <span class="pr-kpi-label">{{ label }}</span>
      <span class="pr-kpi-value">{{ value }}<small v-if="unit" class="pr-kpi-unit">{{ unit }}</small></span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'

defineProps<{
  icon: string
  colorClass: string
  label: string
  value: string | number
  unit?: string
}>()
</script>

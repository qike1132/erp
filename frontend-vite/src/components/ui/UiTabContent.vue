<template>
  <TabsContent :value="value" class="animate-fade-in">
    <slot />
  </TabsContent>
</template>

<script setup lang="ts">
import { TabsContent } from 'reka-ui'

defineProps<{ value: string }>()
</script>

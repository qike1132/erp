<template>
  <div class="mc-seg" role="group" aria-label="按 BOM 过滤产品">
    <button
      v-for="f in options"
      :key="f.value"
      type="button"
      :class="{ active: modelValue === f.value }"
      :aria-pressed="modelValue === f.value"
      @click="model = f.value"
    >
      {{ f.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
// BOM 过滤：由「独立整行的三个大按钮」改为列内紧凑分段控件（.mc-seg，定义在全局 app.css），
// 以便与搜索框同处 .mc-col-tools 一行。取值口径与交互语义完全不变。
type FilterValue = 'all' | 'true' | 'false'

const model = defineModel<FilterValue>({ default: 'all' })

defineProps<{
  options: Array<{ label: string; value: FilterValue }>
}>()
</script>

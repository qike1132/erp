<script setup lang="ts">
/**
 * UiLoadingIcon — 动态加载图标
 *
 * 当 loading=true 时渲染 <UiSpinner />（带尺寸约束），
 * 否则渲染指定的 FontAwesome 图标。
 *
 * Props:
 *   loading  - 是否加载中
 *   icon     - 完成态的 FontAwesome 图标类名（不含 fas fa-）
 *   size     - 图标尺寸（默认 'sm': 14px）
 *
 * 示例：
 *   <UiLoadingIcon :loading="isLoading" icon="download" />
 *   <UiLoadingIcon :loading="isLoading" icon="file-excel" size="sm" />
 */
withDefaults(
  defineProps<{
    loading: boolean
    icon: string
    size?: 'xs' | 'sm' | 'base' | 'lg'
  }>(),
  {
    size: 'sm',
  },
)

const sizeClasses: Record<string, string> = {
  xs: 'text-xs',
  sm: 'text-sm',
  base: 'text-base',
  lg: 'text-lg',
}
</script>

<template>
  <span class="inline-flex relative">
    <i
      v-show="loading"
      class="fas fa-circle-notch fa-spin"
      :class="sizeClasses[size]"
      aria-hidden="true"
    />
    <i v-show="!loading" :class="[`fas fa-${icon}`, sizeClasses[size]]" aria-hidden="true" />
  </span>
</template>

<template>
  <div class="sb-search">
    <FontAwesomeIcon icon="search" class="sb-search-icon" aria-hidden="true" />
    <input
      class="sb-search-input"
      :value="modelValue"
      :placeholder="placeholder"
      :aria-label="ariaLabel || placeholder"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @keyup.enter="emit('search')"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * SearchBox.vue — 带左侧放大镜图标的搜索框（共享组件）
 *
 * 2026-10-07 从 views/stock/components/InventoryToolbar.vue 提取，供
 * 供 /stock（库存汇总）页复用（原 /inventory-query 已并入该页），保持观感与行为一致：
 * 逐字上抛 `update:modelValue`，由**父级**持有搜索词并用防抖副本驱动查询
 * （输入即搜，无需点查询按钮）；回车上抛 `search` 触发一次立即取数。
 * 纯受控组件，本组件不存状态。
 *
 * 注意：`margin-left: auto` 之类的定位由父级负责（本组件不假设自己在一行里靠右）。
 */
withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    ariaLabel?: string
  }>(),
  {
    modelValue: '',
    placeholder: '输入产品名称或 69 码',
    ariaLabel: '',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  search: []
}>()
</script>

<style scoped>
.sb-search {
  position: relative;
  flex-shrink: 0;
}
.sb-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 13px;
  height: 13px;
  color: var(--color-text-muted);
  pointer-events: none;
}
.sb-search-input {
  width: 230px;
  padding: 7px 12px 7px 30px;
  border: 1.5px solid var(--color-border);
  border-radius: 9px;
  background: white;
  font-size: 12.5px;
  font-family: inherit;
  color: var(--color-text);
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.sb-search-input::placeholder { color: var(--color-text-muted); }
.sb-search-input:focus {
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.15);
}
.sb-search-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
</style>

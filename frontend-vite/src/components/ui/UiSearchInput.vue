<script setup lang="ts">
/**
 * UiSearchInput — 带搜索图标的输入框
 *
 * 统一 8 个视图中各自的搜索输入框样式。
 * 与 UiInput 的区别：固定在右侧的搜索图标 + 更宽的默认尺寸。
 *
 * Props:
 *   modelValue   - v-model 绑定
 *   placeholder
 *   disabled
 *
 * Emits:
 *   update:modelValue
 *   search   - 按回车或点击图标时触发
 *   clear    - 清空时触发
 *
 * 示例：
 *   <UiSearchInput v-model="keyword" placeholder="搜索产品..." @search="doSearch" />
 */
const props = withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    disabled?: boolean
  }>(),
  {
    modelValue: '',
    placeholder: '搜索...',
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  search: [query: string]
  clear: []
}>()

function onInput(e: Event) {
  const value = (e.target as HTMLInputElement).value
  emit('update:modelValue', value)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    emit('search', props.modelValue)
  }
}

function onSearchClick() {
  emit('search', props.modelValue)
}

function onClear() {
  emit('update:modelValue', '')
  emit('clear')
}
</script>

<template>
  <div class="relative inline-flex items-center w-full max-w-sm">
    <input
      type="text"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      class="w-full py-2.5 pl-4 pr-10 text-sm bg-slate-50 border-2 border-ocean-light rounded-[var(--radius-input)] transition-colors duration-200 focus:border-primary focus:shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)] focus:outline-none placeholder:text-text-muted disabled:opacity-50 disabled:cursor-not-allowed"
      @input="onInput"
      @keydown="onKeydown"
    />
    <button
      v-if="modelValue"
      type="button"
      class="absolute right-8 top-1/2 -translate-y-1/2 text-text-muted hover:text-danger transition-colors p-1"
      aria-label="清空"
      @click="onClear"
    >
      <FontAwesomeIcon icon="times" class="text-xs" aria-hidden="true" />
    </button>
    <button
      type="button"
      class="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-primary transition-colors p-1"
      aria-label="搜索"
      @click="onSearchClick"
    >
      <FontAwesomeIcon icon="search" class="text-sm" aria-hidden="true" />
    </button>
  </div>
</template>

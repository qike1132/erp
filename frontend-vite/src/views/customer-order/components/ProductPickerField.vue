<template>
  <div class="co-product-wrap">
    <button
      id="co-product"
      ref="fieldRef"
      type="button"
      class="co-product-field"
      :class="{ 'co-product-field-empty': !modelValue }"
      @click="emit('open')"
    >
      <span class="co-product-text">{{ modelValue || '点击选择产品' }}</span>
      <FontAwesomeIcon icon="list" aria-hidden="true" class="co-product-icon" />
    </button>
    <button
      v-if="modelValue"
      type="button"
      class="co-product-clear"
      aria-label="清空已选产品"
      title="清空重选"
      @click="emit('clear')"
    ><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
  </div>
</template>

<script setup lang="ts">
/**
 * 产品字段 —— 整块可点，点开「选择产品」弹窗（2026-10-10 方案 B）。
 *
 * 从 OrderInputPanel 抽出来，一是让录入面板保持在组件行数上限之内，
 * 二是这个字段的交互（点开 / 清空）与录入面板的其余部分没有关系，独立更好测。
 * 它是纯展示：不认识产品搜索，也不认识弹窗，只把点击转成事件。
 */
import { ref } from 'vue'

withDefaults(defineProps<{
  /** 已选产品名；空串表示还没选 */
  modelValue?: string
}>(), {
  modelValue: '',
})

const emit = defineEmits<{
  open: []
  clear: []
}>()

const fieldRef = ref<HTMLButtonElement | null>(null)

defineExpose({ focus: () => fieldRef.value?.focus() })
</script>

<style scoped>
.co-product-wrap { display: flex; align-items: stretch; gap: 6px; }

.co-product-field {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 38px;
  padding: 8px 12px;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  background: white;
  font-size: 14px;
  font-family: inherit;
  color: var(--color-text);
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.co-product-field:hover { border-color: var(--color-primary-400); }
.co-product-field:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.co-product-field-empty .co-product-text { color: var(--color-text-muted); }
.co-product-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.co-product-icon { flex: none; color: var(--color-text-muted); font-size: 13px; }

.co-product-clear {
  flex: none;
  width: 38px;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 10px;
  background: white;
  color: var(--color-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}
.co-product-clear:hover { background: var(--color-danger-50); color: var(--color-danger-500); }
</style>

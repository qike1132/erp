<template>
  <div class="ui-pagination">
    <select
      v-if="showSizeSelector"
      class="ui-page-size"
      :value="pageSize"
      aria-label="每页条数"
      @change="onPageSizeChange"
    >
      <option v-for="n in pageSizeOptions" :key="n" :value="n">{{ n }} 条/页</option>
    </select>

    <span v-if="totalItems != null" class="ui-page-total">共 {{ totalItems }} 条</span>

    <div class="ui-page-nav">
      <button class="ui-page-btn" :disabled="currentPage <= 1" aria-label="上一页" @click="go(currentPage - 1)">
        <FontAwesomeIcon icon="angle-left" aria-hidden="true" />
      </button>
      <span class="ui-page-info">{{ currentPage }} / {{ totalPages }}</span>
      <button class="ui-page-btn" aria-label="下一页" :disabled="currentPage >= totalPages" @click="go(currentPage + 1)">
        <FontAwesomeIcon icon="angle-right" aria-hidden="true" />
      </button>
    </div>

    <span v-if="totalPages > 1" class="ui-page-jump">
      跳至
      <input
        v-model="jumpText"
        class="ui-page-jump-input"
        type="text"
        inputmode="numeric"
        @keyup.enter="jumpToPage"
        @blur="jumpToPage"
      />
      页
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

const props = defineProps<{
  currentPage: number
  totalPages: number
  totalItems?: number
  pageSize?: number
  pageSizeOptions?: number[]
}>()

const emit = defineEmits<{
  'update:currentPage': [page: number]
  'update:pageSize': [size: number]
}>()

/** 只有传入 pageSize 且配置了可选项时才显示每页条数选择器 */
const showSizeSelector = computed(() => props.pageSize != null && !!props.pageSizeOptions?.length)

/** 跳页输入框文本（空字符串 = 未输入） */
const jumpText = ref('')

function go(page: number) {
  emit('update:currentPage', page)
}

function onPageSizeChange(e: Event) {
  emit('update:pageSize', Number((e.target as HTMLSelectElement).value))
}

/** 解析跳页输入并跳转，越界自动收敛到 [1, totalPages] */
function jumpToPage() {
  const raw = jumpText.value.trim()
  jumpText.value = ''
  if (!raw) return
  const n = Number(raw)
  if (!Number.isInteger(n)) return
  const clamped = Math.min(Math.max(n, 1), props.totalPages)
  if (clamped !== props.currentPage) {
    emit('update:currentPage', clamped)
  }
}
</script>

<style scoped>
/* 单行统一分页栏：所有控件同高、同边框、同字号，整体居中成一组 */
.ui-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px 10px;
  border-top: 1px solid var(--color-border-light, #f1f5f9);
}

/* 控件统一样式（下拉 / 按钮 / 输入框） */
.ui-page-size,
.ui-page-btn,
.ui-page-jump-input {
  height: 28px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 6px;
  background: white;
  font-size: 12px;
  color: var(--color-text-secondary);
  font-family: inherit;
  box-sizing: border-box;
}
.ui-page-size {
  padding: 0 8px;
  cursor: pointer;
}
.ui-page-size:hover {
  border-color: var(--color-primary-300);
}

.ui-page-btn {
  width: 30px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}
.ui-page-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
}
.ui-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ui-page-size:focus-visible,
.ui-page-btn:focus-visible,
.ui-page-jump-input:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 1px;
}

.ui-page-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ui-page-info {
  min-width: 44px;
  padding: 0 4px;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.ui-page-total {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* 跳转页码输入 */
.ui-page-jump {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
.ui-page-jump-input {
  width: 44px;
  padding: 0 4px;
  text-align: center;
  color: var(--color-text);
  -moz-appearance: textfield;
  appearance: textfield;
}
.ui-page-jump-input::-webkit-outer-spin-button,
.ui-page-jump-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
</style>

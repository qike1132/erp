<template>
  <div class="co-records-header">
    <span class="co-records-title"><FontAwesomeIcon icon="list-alt" aria-hidden="true" /> 记录列表</span>
    <div class="co-search-tool">
      <span class="co-search">
        <FontAwesomeIcon icon="magnifying-glass" class="co-search-icon" aria-hidden="true" />
        <input
          v-model="keyword"
          class="co-record-search"
          type="text"
          placeholder="搜索 单号 / 客户 / 产品名 / 条码"
          aria-label="搜索记录"
          @keydown.enter="$emit('search')"
        />
        <button
          v-if="keyword"
          class="co-search-clear"
          type="button"
          aria-label="清空搜索"
          @click="$emit('clear')"
        >
          <FontAwesomeIcon icon="xmark" aria-hidden="true" />
        </button>
      </span>
      <UiButton variant="primary" size="sm" @click="$emit('search')">
        <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
      </UiButton>
      <span v-if="!isLoading" class="co-search-count">共 <b>{{ totalRecords }}</b> 条</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'

const props = defineProps<{
  keyword: string
  totalRecords: number
  isLoading: boolean
}>()

const emit = defineEmits<{
  'update:keyword': [value: string]
  search: []
  clear: []
}>()

const keyword = computed({
  get: () => props.keyword,
  set: (v: string) => emit('update:keyword', v),
})
</script>

<style scoped>
.co-records-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
  flex-wrap: wrap;
}
.co-records-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.co-records-title i { color: var(--color-primary-500); }

.co-search-tool {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.co-search {
  position: relative;
  flex: 1;
  min-width: 220px;
  max-width: 420px;
}
.co-record-search {
  width: 100%;
  height: 36px;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 9px;
  background: var(--color-bg, #fff);
  padding: 0 32px 0 32px;
  font-size: 13px;
  color: var(--color-text);
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  font-family: inherit;
}
.co-record-search::placeholder { color: var(--color-text-muted); }
.co-record-search:focus {
  border-color: var(--color-primary-500);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.13);
}
.co-search-icon {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  font-size: 13px;
  pointer-events: none;
}
.co-search-clear {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 17px;
  height: 17px;
  border: none;
  border-radius: 50%;
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-muted);
  font-size: 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  line-height: 1;
}
.co-search-clear:hover { background: var(--color-border-light); color: var(--color-text-secondary); }
.co-search-count {
  font-size: 12px;
  color: var(--color-text-muted);
  white-space: nowrap;
}
.co-search-count b { color: var(--color-text); }
@media (max-width: 640px) {
  .co-search { min-width: 100%; max-width: none; }
  .co-records-header { padding: 10px 12px; }
}
</style>

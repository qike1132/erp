<template>
  <div class="sp-toolbar">
    <div class="sp-search">
      <UiSearchInput
        v-model="kw"
        :placeholder="viewTab === 'daily' ? '搜索日期、客户...' : '搜索产品、SKU、客户...'"
        @clear="kw = ''"
      />
    </div>
    <button class="sp-action-btn" aria-label="导出" @click="emit('export')">导出</button>
    <button class="sp-action-btn sp-action-btn-primary" aria-label="新建" @click="emit('create')">
      <FontAwesomeIcon icon="plus" aria-hidden="true" />新建计划
    </button>
  </div>
</template>

<script setup lang="ts">
// 页面右上角的操作区。
// 月份导航已移到第二行（它作用于整页，属于「看的是哪个月」而非「做一件事」），
// 「新建」加「计划」二字并独占主按钮，与导出拉开主次。
import UiSearchInput from '@/components/ui/UiSearchInput.vue'

defineProps<{
  viewTab: 'daily' | 'summary'
}>()

const emit = defineEmits<{
  'update:globalKw': [v: string]
  export: []
  create: []
}>()

const kw = defineModel<string>('globalKw', { default: '' })
</script>

<style scoped lang="scss">
.sp-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.sp-search {
  width: 240px;
  flex-shrink: 1;
  min-width: 160px;
}

.sp-action-btn {
  padding: 7px 14px;
  border-radius: 9px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  color: var(--color-primary-600);
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  font-family: inherit;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.sp-action-btn:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.sp-action-btn-primary {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  border-color: transparent;
  color: white;
}

.sp-action-btn-primary:hover {
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-800));
  opacity: 0.95;
  box-shadow: 0 4px 12px rgba(91, 141, 239, 0.25);
}
</style>

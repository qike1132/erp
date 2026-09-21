<template>
  <div class="sp-toolbar">
    <div class="sp-nav">
      <button class="sp-nav-btn" aria-label="上一页" @click="emit('prev-month')"><FontAwesomeIcon icon="chevron-left" aria-hidden="true" /></button>
      <span class="sp-nav-label">{{ y }}年{{ String(m).padStart(2, '0') }}月</span>
      <button class="sp-nav-btn" aria-label="下一页" @click="emit('next-month')"><FontAwesomeIcon icon="chevron-right" aria-hidden="true" /></button>
    </div>
    <div class="sp-search">
      <UiSearchInput v-model="kw" :placeholder="viewTab === 'daily' ? '搜索日期、客户...' : '搜索产品、SKU、客户...'" @clear="kw = ''" />
    </div>
    <button class="sp-action-btn" aria-label="导出" @click="emit('export')">导出</button>
    <button class="sp-action-btn sp-action-btn-primary" aria-label="新建" @click="emit('create')"><FontAwesomeIcon icon="plus" aria-hidden="true" />新建</button>
  </div>
</template>

<script setup lang="ts">
import UiSearchInput from '@/components/ui/UiSearchInput.vue'

defineProps<{
  viewTab: 'daily' | 'summary'
  y: number
  m: number
}>()

const emit = defineEmits<{
  'update:globalKw': [v: string]
  'prev-month': []
  'next-month': []
  'export': []
  'create': []
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

.sp-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.sp-search {
  width: 260px;
  flex-shrink: 1;
  min-width: 160px;
}

.sp-nav-btn {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-input, 12px);
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: white;
  cursor: pointer;
  color: var(--color-text-secondary);
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.3s ease, color 0.3s ease, background 0.3s ease;
  flex-shrink: 0;
}

.sp-nav-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sp-nav-label {
  font-weight: 700;
  font-size: 14px;
  color: var(--color-heading);
  min-width: 90px;
  text-align: center;
  user-select: none;
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

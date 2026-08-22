<template>
  <div class="rp-filter-bar">
    <div class="rp-filter-field">
      <label class="rp-filter-label">客户名称</label>
      <UiSelect v-model="filters.customer" placeholder="全部客户" style="width: 160px" :options="customerOptions" />
    </div>
    <div class="rp-filter-field">
      <label class="rp-filter-label">产品名称/SKU</label>
      <input v-model="filters.product" class="rp-filter-input" placeholder="输入产品名称或SKU" aria-label="输入产品名称或SKU" />
    </div>
    <div class="rp-filter-field">
      <label class="rp-filter-label">开始日期</label>
      <UiDatePicker v-model="filters.startDate" style="width: 160px" />
    </div>
    <div class="rp-filter-field">
      <label class="rp-filter-label">结束日期</label>
      <UiDatePicker v-model="filters.endDate" style="width: 160px" />
    </div>
    <div class="rp-filter-actions">
      <button class="rp-action-btn rp-action-primary" aria-label="查询" @click="emit('search')">查询</button>
      <button class="rp-action-btn rp-action-outline" aria-label="重置" @click="emit('reset')">重置</button>
      <button v-if="searched" class="rp-action-btn rp-action-success" aria-label="导出" @click="emit('export')">
        <FontAwesomeIcon icon="download" style="margin-right: 4px" aria-hidden="true" />导出
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'

defineProps<{
  customerOptions: { value: string; label: string }[]
  searched: boolean
}>()

// 显式双向绑定：父组件 v-model:filters 传入，筛选条件就地编辑
const filters = defineModel<{ customer: string; product: string; startDate: string; endDate: string }>('filters', { required: true })

const emit = defineEmits<{
  'search': []
  'reset': []
  'export': []
}>()
</script>

<style scoped>
.rp-filter-bar {
  display: flex;
  gap: 12px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-wrap: wrap;
  align-items: flex-end;
}
.rp-filter-field {
  flex-shrink: 0;
}
.rp-filter-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}
.rp-filter-input {
  width: 180px;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.rp-filter-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.rp-filter-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.rp-filter-actions {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.rp-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
}
.rp-action-primary { color: var(--color-primary-600); }
.rp-action-primary:hover { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.rp-action-outline { }
.rp-action-success { color: var(--color-success-600); border-color: var(--color-success-200); }
.rp-action-success:hover { background: var(--color-success-50); border-color: var(--color-success-300); transform: translateY(-1px); }
</style>
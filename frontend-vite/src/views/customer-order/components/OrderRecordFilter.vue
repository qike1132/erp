<template>
  <div class="co-records-header">
    <div class="co-records-title-group">
      <span class="co-records-title"><FontAwesomeIcon icon="list-alt" aria-hidden="true" /> 记录列表</span>
      <span class="co-record-type-switch">
        <button
          v-for="opt in recordTypeOptions"
          :key="opt.value"
          :class="['co-type-btn', recordType === opt.value && 'active']"
          @click="$emit('change-record-type', opt.value)"
        >{{ opt.label }}</button>
      </span>
    </div>
    <UiButton variant="outline" size="sm" @click="$emit('update:showFilter', !showFilter)">
      <FontAwesomeIcon icon="filter" style="margin-right: 4px" aria-hidden="true" />筛选
    </UiButton>
  </div>

  <div v-if="showFilter" class="co-filter-panel">
    <div class="co-filter-row">
      <div class="co-filter-field">
        <label class="co-label" for="co-filter-customer"><FontAwesomeIcon icon="user" aria-hidden="true" /> 客户</label>
        <UiSelect id="co-filter-customer" label="按客户筛选" :model-value="filterCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" @update:model-value="$emit('update:filterCustomer', $event)" />
      </div>
      <div class="co-filter-field">
        <label class="co-label" for="co-filter-order-type"><FontAwesomeIcon icon="tag" aria-hidden="true" /> 订单类型</label>
        <UiSelect id="co-filter-order-type" label="按订单类型筛选" :model-value="filterOrderType" placeholder="全部" :options="filterOrderTypeOptions" style="width: 100%" @update:model-value="$emit('update:filterOrderType', $event)" />
      </div>
      <div v-if="recordType === 'order'" class="co-filter-field">
        <label class="co-label" for="co-filter-status"><FontAwesomeIcon icon="info-circle" aria-hidden="true" /> 状态</label>
        <UiSelect id="co-filter-status" label="按状态筛选" :model-value="filterStatus" placeholder="全部" :options="statusOptions" style="width: 100%" @update:model-value="$emit('update:filterStatus', $event)" />
      </div>
      <div v-if="recordType === 'order'" class="co-filter-field">
        <label class="co-label" for="co-filter-factory"><FontAwesomeIcon icon="industry" aria-hidden="true" /> 工厂</label>
        <UiSelect id="co-filter-factory" label="按工厂筛选" :model-value="filterFactory" placeholder="全部" :options="factoryOptions" :disabled="factoryDisabled" style="width: 100%" @update:model-value="$emit('update:filterFactory', $event)" />
      </div>
      <div class="co-filter-field">
        <label class="co-label" for="co-filter-start"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> 开始日期</label>
        <UiDatePicker id="co-filter-start" label="开始日期" :model-value="filterStart" style="width: 100%" @update:model-value="$emit('update:filterStart', $event)" />
      </div>
      <div class="co-filter-field">
        <label class="co-label" for="co-filter-end"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> 结束日期</label>
        <UiDatePicker id="co-filter-end" label="结束日期" :model-value="filterEnd" style="width: 100%" @update:model-value="$emit('update:filterEnd', $event)" />
      </div>
      <div class="co-filter-field co-filter-action">
        <UiButton variant="primary" size="sm" @click="$emit('search')">
          <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
        </UiButton>
        <UiButton variant="outline" size="sm" @click="$emit('reset')">
          <FontAwesomeIcon icon="undo" style="margin-right: 4px" aria-hidden="true" />重置
        </UiButton>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'

defineProps<{
  recordType: 'order' | 'stockin'
  recordTypeOptions: { label: string; value: 'order' | 'stockin' }[]
  customerOptions: { label: string; value: string }[]
  filterOrderTypeOptions: { label: string; value: string }[]
  factoryOptions: { label: string; value: string }[]
  factoryDisabled: boolean
  statusOptions: { label: string; value: string }[]
  showFilter: boolean
  filterCustomer: string
  filterOrderType: string
  filterStatus: string
  filterFactory: string
  filterStart: string
  filterEnd: string
}>()

defineEmits<{
  'update:showFilter': [value: boolean]
  'update:filterCustomer': [value: string]
  'update:filterOrderType': [value: string]
  'update:filterStatus': [value: string]
  'update:filterFactory': [value: string]
  'update:filterStart': [value: string]
  'update:filterEnd': [value: string]
  'change-record-type': [value: 'order' | 'stockin']
  search: []
  reset: []
}>()
</script>

<style scoped>
.co-records-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.co-records-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
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
.co-record-type-switch {
  display: inline-flex;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 6px;
  overflow: hidden;
}
.co-record-type-switch .co-type-btn {
  padding: 4px 14px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  background: var(--color-bg, #fff);
  color: var(--color-text-secondary, #64748b);
  cursor: pointer;
  transition: all 0.15s;
}
.co-record-type-switch .co-type-btn.active {
  background: var(--color-primary-500, #3b82f6);
  color: #fff;
}
.co-filter-panel {
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  background: var(--color-surface, #f8fafc);
}
.co-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.co-filter-field {
  min-width: 140px;
  flex: 1;
}
.co-filter-field .co-label {
  font-size: 12px;
  margin-bottom: 4px;
}
.co-filter-action {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
  min-width: auto;
}
.co-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}
@media (max-width: 768px) {
  .co-filter-row { flex-direction: column; }
  .co-filter-field { min-width: 100%; }
}
</style>
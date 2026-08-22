<template>
  <div class="cu-table-wrap">
    <div v-if="isLoading && customers.length === 0" class="cu-empty">
      <UiSpinner />
    </div>
    <template v-else-if="customers.length === 0">
      <div class="cu-empty">
        <FontAwesomeIcon icon="building" aria-hidden="true" />
        <span>暂无客户数据</span>
        <button class="cu-action-btn cu-action-primary" aria-label="立即添加" @click="emit('add')">立即添加</button>
      </div>
    </template>
    <template v-else>
      <div v-if="isFetching" class="cu-fetching-bar"><div class="cu-fetching-progress" /></div>
      <table class="cu-table">
        <thead>
          <tr>
            <th style="text-align: left">客户名称</th>
            <th>联系人</th>
            <th>联系电话</th>
            <th style="text-align: left">地址</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in customers" :key="row.id">
            <td style="text-align: left">
              <div class="cu-customer-cell">
                <div class="cu-customer-avatar">{{ row.name.charAt(0) }}</div>
                <div class="cu-customer-info">
                  <span class="cu-customer-name">{{ row.name }}</span>
                  <span v-if="row.customer_code" class="cu-customer-code">{{ row.customer_code }}</span>
                </div>
              </div>
            </td>
            <td><span :class="row.contact ? 'cu-text-body' : 'cu-text-muted'">{{ row.contact || '未填写' }}</span></td>
            <td><span :class="row.phone ? 'cu-text-body' : 'cu-text-muted'">{{ row.phone || '未填写' }}</span></td>
            <td style="text-align: left"><span :class="row.address ? 'cu-text-body' : 'cu-text-muted'">{{ row.address || '未填写' }}</span></td>
            <td>
              <span :class="['cu-status', row.status ? 'cu-status-on' : 'cu-status-off']">
                <i class="cu-dot" />{{ row.status ? '启用' : '停用' }}
              </span>
            </td>
            <td><span class="cu-text-muted">{{ formatDate(row.create_time) }}</span></td>
            <td>
              <div class="cu-actions">
                <button class="cu-icon-btn cu-icon-edit" title="编辑" aria-label="编辑" @click="emit('edit', row)"><FontAwesomeIcon icon="pen-to-square" aria-hidden="true" /></button>
                <button class="cu-icon-btn cu-icon-toggle" title="切换状态" aria-label="切换状态" @click="emit('toggle', row)"><FontAwesomeIcon :icon="row.status ? 'lock' : 'lock-open'" aria-hidden="true" /></button>
                <button class="cu-icon-btn cu-icon-delete" title="删除" aria-label="删除" @click="emit('delete', row)"><FontAwesomeIcon icon="trash" aria-hidden="true" /></button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <UiPagination v-if="totalItems > perPage" :current-page="currentPage" :total-pages="totalPages" :total-items="totalItems" @update:current-page="emit('page', $event)" />
    </template>
  </div>
</template>

<script setup lang="ts">
import type { Customer } from '@/types'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import { formatDate } from '@/utils/format'

defineProps<{
  customers: Customer[]
  isLoading: boolean
  isFetching: boolean
  totalItems: number
  perPage: number
  currentPage: number
  totalPages: number
}>()

const emit = defineEmits<{
  add: []
  edit: [row: Customer]
  toggle: [row: Customer]
  delete: [row: Customer]
  page: [page: number]
}>()
</script>

<style scoped>
.cu-table-wrap {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.cu-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.cu-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary);
  text-align: center;
}
.cu-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.cu-table tbody tr:hover {
  background: var(--color-primary-50);
}
.cu-customer-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cu-customer-avatar {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.cu-customer-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cu-customer-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
}
.cu-customer-code {
  font-size: 11px;
  color: var(--color-text-muted);
  font-family: 'SF Mono', 'Fira Code', monospace;
  letter-spacing: 0.02em;
}
.cu-text-body { font-size: 13px; color: var(--color-text); }
.cu-text-muted { font-size: 13px; color: var(--color-text-muted); font-variant-numeric: tabular-nums; }
.cu-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}
.cu-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.cu-status-on { color: var(--color-success-600); }
.cu-status-on .cu-dot { background: var(--color-success-500); box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.15); }
.cu-status-off { color: var(--color-text-muted); }
.cu-status-off .cu-dot { background: var(--color-border); }
.cu-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.cu-icon-btn {
  width: 30px;
  height: 30px;
  border: none;
  background: transparent;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--color-text-muted);
  transition: background 0.2s ease, color 0.2s ease;
  font-size: 13px;
}
.cu-icon-btn:hover { background: var(--color-border-light); }
.cu-icon-edit:hover { color: var(--color-primary-500); background: var(--color-primary-50); }
.cu-icon-toggle:hover { color: var(--color-warning-500); background: var(--color-warning-50); }
.cu-icon-delete:hover { color: var(--color-danger-500); background: var(--color-danger-50); }
.cu-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.cu-empty i { font-size: 28px; opacity: 0.5; }
.cu-empty span { font-size: 14px; }
.cu-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.cu-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: cu-progress-slide 1s ease-in-out infinite;
}
@keyframes cu-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
.cu-action-btn {
  border-radius: 9px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light);
  background: white;
  font-size: 12px;
  font-weight: 600;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  cursor: pointer;
  color: var(--color-text);
  font-family: inherit;
}
.cu-action-btn:hover {
  transform: translateY(-1px);
}
.cu-action-primary {
  color: var(--color-primary-600);
}
.cu-action-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
}
</style>
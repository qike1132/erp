<template>
  <div class="cu-table-wrap">
    <UiDataTable
      :data="customers"
      :columns="customerColumns"
      :loading="isLoading"
      paginator
      :rows="perPage"
      :total-records="totalItems"
      :current-page="currentPage"
      :page-size-options="[]"
      hide-paginator-on-single-page
      row-key="id"
      empty-message="暂无客户数据"
      @page="onPageChange"
    >
      <template #empty>
        <div class="cu-empty">
          <FontAwesomeIcon icon="building" aria-hidden="true" />
          <span>暂无客户数据</span>
          <button class="cu-action-btn cu-action-primary" aria-label="立即添加" @click="emit('add')">立即添加</button>
        </div>
      </template>
      <template #column-body-name="{ row }">
        <div class="cu-customer-cell">
          <div class="cu-customer-avatar">{{ (row as Customer).name.charAt(0) }}</div>
          <div class="cu-customer-info">
            <span class="cu-customer-name">{{ (row as Customer).name }}</span>
            <span v-if="(row as Customer).customer_code" class="cu-customer-code">{{ (row as Customer).customer_code }}</span>
          </div>
        </div>
      </template>
      <template #column-body-contact="{ row }">
        <span :class="(row as Customer).contact ? 'cu-text-body' : 'cu-text-muted'">{{ (row as Customer).contact || '未填写' }}</span>
      </template>
      <template #column-body-phone="{ row }">
        <span :class="(row as Customer).phone ? 'cu-text-body' : 'cu-text-muted'">{{ (row as Customer).phone || '未填写' }}</span>
      </template>
      <template #column-body-address="{ row }">
        <span :class="(row as Customer).address ? 'cu-text-body' : 'cu-text-muted'">{{ (row as Customer).address || '未填写' }}</span>
      </template>
      <template #column-body-status="{ row }">
        <span :class="['cu-status', (row as Customer).status ? 'cu-status-on' : 'cu-status-off']">
          <i class="cu-dot" />{{ (row as Customer).status ? '启用' : '停用' }}
        </span>
      </template>
      <template #column-body-create_time="{ row }">
        <span class="cu-text-muted">{{ formatDate((row as Customer).create_time) }}</span>
      </template>
      <template #column-body-actions="{ row }">
        <div class="cu-actions">
          <button class="cu-icon-btn cu-icon-edit" title="编辑" aria-label="编辑" @click="emit('edit', row as Customer)"><FontAwesomeIcon icon="pen-to-square" aria-hidden="true" /></button>
          <button class="cu-icon-btn cu-icon-toggle" title="切换状态" aria-label="切换状态" @click="emit('toggle', row as Customer)"><FontAwesomeIcon :icon="(row as Customer).status ? 'lock' : 'lock-open'" aria-hidden="true" /></button>
          <button class="cu-icon-btn cu-icon-delete" title="删除" aria-label="删除" @click="emit('delete', row as Customer)"><FontAwesomeIcon icon="trash" aria-hidden="true" /></button>
        </div>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
/**
 * CustomerTable.vue — 客户列表（UiDataTable 统一表格）
 *
 * OPT-10b：由手写 <table> 迁移到 UiDataTable（与 UserTable 同构），
 * 保留客户名首字头像、状态圆点、空态「立即添加」等既有视觉。
 * 分页契约：UiDataTable 的 page 事件是 0 基页码 + rows，此处转换为
 * 父组件 currentPage = $event（1 基）期望的形式，父组件无需改动。
 */
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { Customer } from '@/types'
import { formatDate } from '@/utils/format'

defineProps<{
  customers: Customer[]
  isLoading: boolean
  totalItems: number
  perPage: number
  /** 受控页码（1 基），由父组件的 currentPage 驱动，避免表格内部分页与回源页码失步 */
  currentPage: number
}>()

const emit = defineEmits<{
  add: []
  edit: [row: Customer]
  toggle: [row: Customer]
  delete: [row: Customer]
  page: [page: number]
}>()

const customerColumns: TableColumn[] = [
  { field: 'name', header: '客户名称', align: 'left' },
  { field: 'contact', header: '联系人', align: 'center' },
  { field: 'phone', header: '联系电话', align: 'center' },
  { field: 'address', header: '地址', align: 'left' },
  { field: 'status', header: '状态', align: 'center' },
  { field: 'create_time', header: '创建时间', align: 'center' },
  { field: 'actions', header: '操作', align: 'center' },
]

/** UiDataTable 分页事件（0 基）→ 父组件 currentPage（1 基） */
function onPageChange(event: { page: number }) {
  emit('page', event.page + 1)
}
</script>

<style scoped>
.cu-table-wrap {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.cu-customer-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.cu-customer-avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.cu-customer-info {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.cu-customer-name {
  font-weight: 600;
  color: var(--color-text);
}
.cu-customer-code {
  font-size: 11px;
  color: var(--color-text-muted);
}
.cu-text-body {
  color: var(--color-text);
}
.cu-text-muted {
  color: var(--color-text-muted);
}
.cu-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
}
.cu-status-on {
  color: var(--color-success-600, #059669);
}
.cu-status-off {
  color: var(--color-text-muted);
}
.cu-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}
.cu-actions {
  display: flex;
  gap: 6px;
  justify-content: center;
}
.cu-icon-btn {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  border: 2px solid transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
}
.cu-icon-edit {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.cu-icon-edit:hover {
  background: var(--color-primary-500);
  color: white;
  transform: translateY(-1px);
}
.cu-icon-toggle {
  background: var(--color-warning-50, #fef3c7);
  color: var(--color-warning-700, #b45309);
}
.cu-icon-toggle:hover {
  background: var(--color-warning-500, #f59e0b);
  color: white;
  transform: translateY(-1px);
}
.cu-icon-delete {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
}
.cu-icon-delete:hover {
  background: var(--color-danger-500);
  color: white;
  transform: translateY(-1px);
}
.cu-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text);
}
.cu-action-primary {
  color: var(--color-primary-600);
}
.cu-action-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.cu-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}
.cu-empty i {
  font-size: 28px;
  opacity: 0.5;
}
</style>

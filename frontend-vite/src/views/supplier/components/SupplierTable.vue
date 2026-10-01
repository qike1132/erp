<template>
  <div class="sp-content">
    <UiDataTable
      :data="suppliers"
      :columns="supplierColumns"
      :loading="isLoading"
      paginator
      :rows="perPage"
      :total-records="totalItems"
      row-key="id"
      :empty-message="hasSearch ? '没有匹配的供应商' : '暂无供应商，请先添加'"
      @page="onPageChange"
    >
      <template #column-body-name="{ row }">
        <span class="sp-name">{{ (row as Supplier).name }}</span>
      </template>
      <template #column-body-contact_person="{ row }">
        {{ (row as Supplier).contact_person || '-' }}
      </template>
      <template #column-body-phone="{ row }">
        {{ (row as Supplier).phone || '-' }}
      </template>
      <template #column-body-address="{ row }">
        {{ (row as Supplier).address || '-' }}
      </template>
      <template #column-body-created_at="{ row }">
        {{ formatDate((row as Supplier).created_at) }}
      </template>
      <template #column-body-status="{ row }">
        <span
          class="sp-status-badge"
          :class="(row as Supplier).status ? 'sp-status-active' : 'sp-status-inactive'"
          :title="(row as Supplier).status ? '点击禁用' : '点击启用'"
          @click="emit('toggle', row as Supplier)"
        >{{ (row as Supplier).status ? '启用' : '禁用' }}</span>
      </template>
      <template #column-body-actions="{ row }">
        <div class="sp-action-group">
          <button class="sp-action-btn sp-action-edit" title="编辑" aria-label="编辑" @click="emit('edit', row as Supplier)">
            <FontAwesomeIcon icon="edit" aria-hidden="true" />
          </button>
          <button
            class="sp-action-btn sp-action-delete"
            title="删除"
            :disabled="actionId === (row as Supplier).id"
            aria-label="删除"
            @click="emit('delete', row as Supplier)"
          >
            <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
          </button>
        </div>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
/**
 * SupplierTable.vue — 供应商列表（UiDataTable 统一表格）
 *
 * OPT-10b：由手写 <table> 迁移到 UiDataTable（与 UserTable 同构）。
 * 分页契约：UiDataTable 的 page 事件是 0 基页码 + rows，此处转换为父组件
 * goPage（1 基）期望的形式，父组件无需改动。
 * 服务端分页：rows/pagination 由 useSupplier 管理经 props 下发。
 */
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { Supplier } from '@/types'
import { formatDate } from '@/utils/format'

defineProps<{
  suppliers: Supplier[]
  isLoading: boolean
  hasSearch: boolean
  actionId: number | ''
  totalItems: number
  perPage: number
}>()

const emit = defineEmits<{
  toggle: [row: Supplier]
  edit: [row: Supplier]
  delete: [row: Supplier]
  page: [page: number]
}>()

const supplierColumns: TableColumn[] = [
  { field: 'name', header: '供应商名称', align: 'left' },
  { field: 'contact_person', header: '联系人', align: 'left' },
  { field: 'phone', header: '联系电话', align: 'left' },
  { field: 'address', header: '地址', align: 'left' },
  { field: 'created_at', header: '创建时间', align: 'left' },
  { field: 'status', header: '状态', align: 'center' },
  { field: 'actions', header: '操作', align: 'right' },
]

/** UiDataTable 分页事件（0 基）→ 父组件 goPage（1 基） */
function onPageChange(event: { page: number }) {
  emit('page', event.page + 1)
}
</script>

<style scoped>
.sp-name {
  font-weight: 600;
  color: var(--color-text);
}
.sp-status-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease, color 0.2s ease, transform 0.2s ease;
  text-align: center;
  min-width: 56px;
}
.sp-status-active {
  background: var(--color-success-50, #ecfdf5);
  color: var(--color-success-700, #047857);
  border: 1px solid var(--color-success-200, #a7f3d0);
}
.sp-status-active:hover {
  background: var(--color-danger-50, #fef2f2);
  color: var(--color-danger-700, #b91c1c);
  border-color: var(--color-danger-200, #fecaca);
  transform: translateY(-1px);
}
.sp-status-inactive {
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-muted, #94a3b8);
  border: 1px solid var(--color-border-light, #e2e8f0);
}
.sp-status-inactive:hover {
  background: var(--color-success-50, #ecfdf5);
  color: var(--color-success-700, #047857);
  border-color: var(--color-success-200, #a7f3d0);
  transform: translateY(-1px);
}
.sp-action-group {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.sp-action-edit,
.sp-action-delete {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  border: 2px solid transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  cursor: pointer;
  padding: 0;
}
.sp-action-edit {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  border-color: var(--color-primary-200);
}
.sp-action-edit:hover {
  background: var(--color-primary-500);
  color: white;
  border-color: transparent;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 148, 191, 0.25);
}
.sp-action-delete {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
  border-color: var(--color-danger-200);
}
.sp-action-delete:hover {
  background: var(--color-danger-500);
  color: white;
  border-color: transparent;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(234, 84, 85, 0.25);
}
.sp-action-delete:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
</style>

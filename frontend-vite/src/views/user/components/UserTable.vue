<template>
  <div class="us-col-scroll">
    <UiDataTable
      :data="users"
      :columns="userColumns"
      :loading="isLoading"
      paginator
      :rows="perPage"
      :total-records="totalItems"
      :row-key="'id'"
      @page="onPageChange"
    >
      <template #empty>
        <div class="us-empty">
          <FontAwesomeIcon icon="users" aria-hidden="true" />
          <span>暂无用户</span>
        </div>
      </template>
      <template #column-body-is_super="{ row }">
        <span :class="['us-badge', (row as UserRow).is_super ? 'us-badge-danger' : 'us-badge-info']">
          {{ (row as UserRow).is_super ? '超级管理员' : '普通用户' }}
        </span>
      </template>
      <template #column-body-factory="{ row }">
        <span v-if="(row as UserRow).factory" :class="['us-badge', 'us-badge-factory']">{{ (row as UserRow).factory }}</span>
        <span v-else class="us-badge-muted-text">-</span>
      </template>
      <template #column-body-status="{ row }">
        <span :class="['us-badge', (row as UserRow).status !== false ? 'us-badge-success' : 'us-badge-muted']">
          {{ (row as UserRow).status !== false ? '启用' : '禁用' }}
        </span>
      </template>
      <template #column-body-create_time="{ row }">
        {{ formatDate((row as UserRow).create_time) }}
      </template>
      <template #column-body-actions="{ row }">
        <div class="us-action-group">
          <button class="us-action-btn us-action-primary" @click="openPermissionDialog(row as UserRow)" aria-label="权限">权限</button>
          <button class="us-action-btn us-action-primary" @click="openEditDialog(row as UserRow)" aria-label="编辑">编辑</button>
          <button class="us-action-btn us-action-primary" :disabled="actionId === (row as UserRow).id" @click="handleToggle(row as UserRow)" :aria-label="(row as UserRow).status !== false ? '禁用' : '启用'">
            {{ (row as UserRow).status !== false ? '禁用' : '启用' }}
          </button>
          <button class="us-action-btn us-action-danger" :disabled="actionId === (row as UserRow).id || (row as UserRow).is_super" @click="handleDelete(row as UserRow)" aria-label="删除">
            删除
          </button>
        </div>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
/**
 * UserTable.vue — 用户列表（右栏）
 *
 * 从 UserView.vue 拆出：UiDataTable 分页表格 + 角色/工厂/状态徽章 + 行操作按钮。
 * 分页与行操作通过 emit 交回父组件处理。
 */
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { formatDate } from '@/utils/format'
import type { User } from '@/types'
import type { UserRow } from '@/views/user/composables/useUserManagement'

defineProps<{
  /** 当前页用户列表 */
  users: User[]
  /** 加载中 */
  isLoading: boolean
  /** 每页条数 */
  perPage: number
  /** 用户总数 */
  totalItems: number
  /** 行操作进行中的用户 id（按钮禁用态） */
  actionId: number | ''
}>()

const emit = defineEmits<{
  /** 分页变化 */
  page: [event: { page: number; rows: number }]
  /** 打开权限分配弹窗 */
  openPermission: [row: UserRow]
  /** 打开编辑弹窗 */
  openEdit: [row: UserRow]
  /** 启用/禁用切换 */
  toggle: [row: UserRow]
  /** 删除 */
  delete: [row: UserRow]
}>()

/** UiDataTable 列定义 */
const userColumns: TableColumn[] = [
  { field: 'username', header: '用户名', align: 'left' },
  { field: 'is_super', header: '角色', align: 'center' },
  { field: 'factory', header: '工厂', align: 'center' },
  { field: 'status', header: '状态', align: 'center' },
  { field: 'create_time', header: '创建时间', align: 'left' },
  { field: 'actions', header: '操作', align: 'right' },
]

/** UiDataTable 分页变化处理：交给父组件更新查询 */
function onPageChange(event: { page: number; rows: number }) {
  emit('page', event)
}

/** 打开权限分配弹窗 */
function openPermissionDialog(row: UserRow) {
  emit('openPermission', row)
}

/** 打开编辑用户弹窗 */
function openEditDialog(row: UserRow) {
  emit('openEdit', row)
}

/** 启用/禁用切换 */
function handleToggle(row: UserRow) {
  emit('toggle', row)
}

/** 删除用户 */
function handleDelete(row: UserRow) {
  emit('delete', row)
}
</script>

<style scoped>
.us-col-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 16px 20px;
}

/* Badge */
.us-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.us-badge-info {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.us-badge-danger {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
}
.us-badge-success {
  background: var(--color-success-50);
  color: var(--color-success-600);
}
.us-badge-muted {
  background: var(--color-border-light, #f1f5f9);
  color: var(--color-text-muted);
}
.us-badge-factory {
  background: var(--color-warning-50, #fef3c7);
  color: var(--color-warning-700, #b45309);
}
.us-badge-muted-text {
  color: var(--color-text-muted);
  font-size: 13px;
}

/* Action Buttons */
.us-action-group {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
  flex-wrap: wrap;
}
.us-action-btn {
  padding: 5px 10px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
  margin-right: 4px;
}
.us-action-primary {
  color: var(--color-primary-600);
}
.us-action-primary:hover:not(:disabled) {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.us-action-danger {
  color: var(--color-danger-500);
}
.us-action-danger:hover:not(:disabled) {
  background: var(--color-danger-50);
  border-color: var(--color-danger-200);
  transform: translateY(-1px);
}
.us-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Empty State */
.us-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.us-empty i {
  font-size: 28px;
  opacity: 0.5;
}
.us-empty span {
  font-size: 14px;
}
</style>

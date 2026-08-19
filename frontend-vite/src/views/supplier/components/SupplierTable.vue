<template>
  <div class="sp-content">
    <div v-if="isLoading && suppliers.length === 0" class="sp-loading-state">
      <UiSpinner />
    </div>

    <div v-else-if="suppliers.length === 0" class="sp-empty-state">
      <FontAwesomeIcon icon="truck" aria-hidden="true" />
      <span>{{ hasSearch ? '没有匹配的供应商' : '暂无供应商，请先添加' }}</span>
      <small v-if="hasSearch">试试其他关键词</small>
    </div>

    <div v-else class="sp-table-wrap">
      <div v-if="isFetching" class="sp-fetching-bar"><div class="sp-fetching-progress" /></div>
      <table>
        <thead>
          <tr>
            <th style="text-align: left">供应商名称</th>
            <th style="text-align: left">联系人</th>
            <th style="text-align: left">联系电话</th>
            <th style="text-align: left">地址</th>
            <th style="text-align: left">创建时间</th>
            <th style="text-align: center">状态</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in suppliers" :key="row.id">
            <td>
              <span class="sp-name">{{ row.name }}</span>
            </td>
            <td>{{ row.contact_person || '-' }}</td>
            <td>{{ row.phone || '-' }}</td>
            <td>{{ row.address || '-' }}</td>
            <td>{{ formatDate(row.created_at) }}</td>
            <td>
              <span
                class="sp-status-badge"
                :class="row.status ? 'sp-status-active' : 'sp-status-inactive'"
                :title="row.status ? '点击禁用' : '点击启用'"
                @click="emit('toggle', row)"
              >{{ row.status ? '启用' : '禁用' }}</span>
            </td>
            <td>
              <div class="sp-action-group">
                <button class="sp-action-btn sp-action-edit" title="编辑" @click="emit('edit', row)" aria-label="编辑">
                  <FontAwesomeIcon icon="edit" aria-hidden="true" />
                </button>
                <button
                  class="sp-action-btn sp-action-delete"
                  title="删除"
                  :disabled="actionId === row.id"
                  @click="emit('delete', row)"
                 aria-label="删除">
                  <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <UiPagination v-if="totalItems > perPage" :current-page="currentPage" :total-pages="totalPages" :total-items="totalItems" @update:current-page="emit('page', $event)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Supplier } from '@/types'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import { formatDate } from '@/utils/format'

defineProps<{
  suppliers: Supplier[]
  isLoading: boolean
  isFetching: boolean
  hasSearch: boolean
  actionId: number | ''
  totalItems: number
  perPage: number
  currentPage: number
  totalPages: number
}>()

const emit = defineEmits<{
  toggle: [row: Supplier]
  edit: [row: Supplier]
  delete: [row: Supplier]
  page: [page: number]
}>()
</script>

<style scoped>
.sp-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.sp-table-wrap {
  padding: 0 24px 24px;
}
.sp-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.sp-table-wrap thead th {
  padding: 10px 14px;
  background: var(--color-surface, #f8fafc);
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}
.sp-table-wrap tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  color: var(--color-text);
  vertical-align: middle;
  transition: background 0.2s ease;
}
.sp-table-wrap tbody tr:last-child td {
  border-bottom: none;
}
.sp-table-wrap tbody tr:hover td {
  background: var(--color-primary-50);
}
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
.sp-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
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
.sp-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}
.sp-empty-state i {
  font-size: 28px;
  opacity: 0.5;
}
.sp-empty-state small {
  font-size: 12px;
  opacity: 0.6;
}
.sp-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}
.sp-loading-state i {
  font-size: 20px;
}
.sp-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.sp-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: sp-progress-slide 1s ease-in-out infinite;
}
@keyframes sp-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
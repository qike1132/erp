<template>
  <div class="sp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <button class="sp-action-btn sp-action-btn-primary" aria-label="添加供应商" @click="formOpen = true">
          <FontAwesomeIcon icon="plus" aria-hidden="true" /> 添加供应商
        </button>
      </div>

      <div class="sp-toolbar">
        <div class="sp-search-wrapper">
          <UiSearchInput v-model="searchTerm" placeholder="搜索供应商名称..." @search="onSearchInput" @clear="clearSearch" /></div>
      </div>

      <SupplierTable
        :suppliers="suppliers"
        :is-loading="isLoading"
        :is-fetching="isFetching"
        :has-search="!!searchTerm"
        :action-id="actionId"
        :total-items="totalItems"
        :per-page="perPage"
        :current-page="currentPage"
        :total-pages="totalPages"
        @toggle="handleToggle"
        @edit="openEditDialog"
        @delete="handleDelete"
        @page="goPage"
      />
    </div>

    <SupplierFormDialog
      :open="formOpen"
      mode="add"
      :submitting="submitting"
      v-model:form="form"
      @update:open="formOpen = $event"
      @submit="handleAdd"
    />

    <SupplierFormDialog
      :open="editDialogVisible"
      mode="edit"
      :submitting="editSubmitting"
      v-model:form="editForm"
      @update:open="editDialogVisible = $event"
      @submit="handleEdit"
    />

    <UiConfirmDialog
      :open="confirmDialog.open"
      :text="confirmDialog.text"
      :sub="confirmDialog.sub"
      :type="confirmDialog.type"
      @confirm="confirmDialog.onConfirm"
      @cancel="confirmDialog.onCancel"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * SupplierView.vue — 供应商管理页面
 *
 * 职责：
 * - 展示供应商列表（服务端分页 + 搜索防抖）
 * - 新增 / 编辑 / 删除供应商
 * - 使用 TanStack Vue Query 管理服务端状态
 */
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'

import SupplierTable from './components/SupplierTable.vue'
import SupplierFormDialog from './components/SupplierFormDialog.vue'
import { useSupplier } from './composables/useSupplier'

const {
  actionId,
  confirmDialog,
  searchTerm,
  currentPage,
  perPage,
  onSearchInput,
  clearSearch,
  isLoading,
  isFetching,
  suppliers,
  totalItems,
  totalPages,
  goPage,
  formOpen,
  submitting,
  form,
  handleAdd,
  handleDelete,
  handleToggle,
  editDialogVisible,
  editSubmitting,
  editForm,
  openEditDialog,
  handleEdit,
} = useSupplier()
</script>

<style scoped>
.sp-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
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

.sp-action-btn-primary {
  color: var(--color-primary-600);
}

.sp-action-btn-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}

.sp-toolbar {
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  flex-shrink: 0;
}

.sp-search-wrapper {
  position: relative;
}
</style>

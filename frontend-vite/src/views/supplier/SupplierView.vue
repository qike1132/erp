<template>
  <div class="sp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <button class="sp-action-btn sp-action-btn-primary" aria-label="添加供应商" @click="formOpen = true">
          <FontAwesomeIcon icon="plus" aria-hidden="true" /> 添加供应商
        </button>

        <div class="page-toolbar-right">
          <div class="sp-search-wrapper">
            <UiSearchInput
              v-model="searchTerm"
              placeholder="搜索供应商名称..."
              @update:model-value="onSearchInput"
              @clear="clearSearch"
            />
          </div>
        </div>
      </div>

      <SupplierTable
        :suppliers="suppliers"
        :is-loading="isLoading"
        :has-search="!!searchTerm"
        :action-id="actionId"
        :total-items="totalItems"
        :per-page="perPage"
        :current-page="currentPage"
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
  suppliers,
  totalItems,
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
/* 本页卡片直角（应用户要求）：全局 .page-card 在 @layer components 里是 18px，
   scoped 未分层样式在层叠中优先于分层样式，此处覆盖只影响 /supplier */
.page-card {
  border-radius: 0;
}

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

/* 固定宽度：UiSearchInput 根节点是 w-full，放在「宽度由内容决定」的
   .page-toolbar-right 里会形成百分比循环，宽度不确定。显式给宽即可 */
.sp-search-wrapper {
  width: 320px;
}
</style>

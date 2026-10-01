<template>
  <div class="cu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->
      <div class="page-card-header">
        <div class="cu-tabs">
          <button class="cu-tab-btn active" aria-label="新建客户" @click="openForm('add')">
            <FontAwesomeIcon icon="plus" aria-hidden="true" /> 新建客户
          </button>
        </div>
      </div>

      <!-- 数据表格 -->
      <CustomerTable
        :customers="customers"
        :is-loading="isLoading"
        :total-items="totalItems"
        :per-page="perPage"
        @add="openForm('add')"
        @edit="(row) => openForm('edit', row)"
        @toggle="handleToggle"
        @delete="handleDelete"
        @page="currentPage = $event"
      />
    </div>

    <!-- 新建/编辑弹窗 -->
    <CustomerFormDialog
      :open="formVisible"
      :mode="formMode"
      :submitting="submitting"
      v-model:form="form"
      @update:open="formVisible = $event"
      @submit="handleSubmit"
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
 * CustomerView.vue — 客户管理页面
 *
 * 职责：
 * - 展示客户列表（服务端分页 + 搜索防抖 + 状态筛选）
 * - 新增 / 编辑 / 删除客户，切换启用/停用状态
 * - 使用 useApiMutation 统一管理增删改操作
 */
import CustomerTable from './components/CustomerTable.vue'
import CustomerFormDialog from './components/CustomerFormDialog.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useCustomer } from './composables/useCustomer'

const {
  currentPage,
  perPage,
  isLoading,
  isFetching,
  customers,
  totalItems,
  totalPages,
  formVisible,
  formMode,
  submitting,
  form,
  openForm,
  handleSubmit,
  handleToggle,
  handleDelete,
  confirmDialog,
} = useCustomer()
</script>

<style scoped>
.cu-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Tabs */
.cu-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}

.cu-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}

.cu-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.cu-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91,141,239,0.2);
  transform: translateY(-1px);
}
</style>

<template>
  <div class="us-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->

      <!-- 双栏主体 -->
      <div class="us-body">
        <!-- 左栏：添加用户（拆分为子组件） -->
        <div class="us-col">
          <UserCreateForm />
        </div>

        <!-- 右栏：用户列表（拆分为子组件） -->
        <div class="us-col">
          <UserTable
            :users="users"
            :is-loading="isLoading"
            :per-page="perPage"
            :total-items="totalItems"
            :action-id="actionId"
            @page="onPageChange"
            @open-permission="openPermissionDialog"
            @open-edit="openEditDialog"
            @toggle="handleToggle"
            @delete="handleDelete"
          />
        </div>
      </div>
    </div>

    <!-- 编辑用户弹窗（工厂/部门，拆分为子组件） -->
    <UserEditDialog
      v-model:open="editDialogVisible"
      :edit-target-id="editTargetId"
      :edit-target-name="editTargetName"
      :initial-factory="editInitialFactory"
      :initial-department="editInitialDepartment"
    />

    <!-- 权限分配弹窗（拆分为子组件） -->
    <UserPermissionDialog
      v-model:open="permDialogVisible"
      :perm-target-name="permTargetName"
      :permission-sections="permissionSections"
      :perm-checked-keys="permCheckedKeys"
      :perm-is-all-checked="permIsAllChecked"
      :perm-submitting="permSubmitting"
      :is-perm-expanded="isPermExpanded"
      :toggle-perm-expand="togglePermExpand"
      :is-perm-checked="isPermChecked"
      :toggle-perm-node="togglePermNode"
      :get-perm-child-count="getPermChildCount"
      :toggle-all-perms="toggleAllPerms"
      :handle-save-permission="handleSavePermission"
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
 * UserView.vue — 用户管理页面
 *
 * 职责：
 * - 左栏：添加新用户（用户名、密码、超级管理员勾选）
 * - 右栏：用户列表（分页、启用/禁用切换、删除）
 * - 权限分配弹窗：按模块分组展示权限树，支持全选/级联选择
 *
 * 页面逻辑下沉到 composables/useUserManagement.ts；新增表单/用户表格/
 * 编辑弹窗/权限弹窗分别拆分为 components/ 下的子组件。
 */
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import UserCreateForm from '@/views/user/components/UserCreateForm.vue'
import UserTable from '@/views/user/components/UserTable.vue'
import UserEditDialog from '@/views/user/components/UserEditDialog.vue'
import UserPermissionDialog from '@/views/user/components/UserPermissionDialog.vue'
import { useUserManagement } from '@/views/user/composables/useUserManagement'

const {
  actionId,
  confirmDialog,
  perPage,
  isLoading,
  users,
  totalItems,
  onPageChange,
  handleToggle,
  handleDelete,
  editDialogVisible,
  editTargetId,
  editTargetName,
  editInitialFactory,
  editInitialDepartment,
  openEditDialog,
  permDialogVisible,
  permSubmitting,
  permCheckedKeys,
  permTargetName,
  permissionSections,
  isPermExpanded,
  togglePermExpand,
  isPermChecked,
  togglePermNode,
  getPermChildCount,
  permIsAllChecked,
  toggleAllPerms,
  openPermissionDialog,
  handleSavePermission,
} = useUserManagement()
</script>

<style scoped>
/* Container */
.us-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card Header */
.us-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.us-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.us-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* Icon Box */
.us-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.us-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* Body */
.us-body {
  display: grid;
  grid-template-columns: 320px 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Column */
.us-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.us-col + .us-col {
  border-left: 1px solid var(--color-border-light, #f1f5f9);
}

/* Count Badge */
.us-count-badge {
  margin-left: auto;
  padding: 4px 12px;
  border-radius: 20px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  font-size: 12px;
  font-weight: 600;
}
</style>

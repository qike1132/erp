<template>
  <!-- 权限分配弹窗 -->
  <UiDialog :open="permDialogVisible" title="分配权限" max-width-class="max-w-[640px]" @update:open="permDialogVisible = $event">
    <div class="us-perm-header">
      <div class="us-perm-user">{{ permTargetName }}</div>
      <button class="us-perm-toggle-all" @click="toggleAllPerms" :aria-label="permIsAllChecked ? '取消全选' : '全选'">{{ permIsAllChecked ? '取消全选' : '全选' }}</button>
    </div>
    <div class="us-perm-tree">
      <div v-for="sec in permissionSections" :key="sec.key" class="us-perm-section">
        <div class="us-perm-section-title">{{ sec.name }}</div>
        <div v-for="node in sec.items" :key="node.id" class="us-perm-group">
          <div class="us-perm-group-header" @click="node.children?.length ? togglePermExpand(node.id) : togglePermNode(node.id)">
            <UiCheckbox :checked="isPermChecked(node.id)" @update:checked="togglePermNode(node.id)" @click.stop />
            <span class="us-perm-group-name">
              <FontAwesomeIcon v-if="node.icon" :icon="node.icon.replace('fa-', '')" class="us-perm-group-icon" />
              {{ node.name }}
            </span>
            <span v-if="node.children?.length" class="us-perm-group-count">{{ getPermChildCount(node, permCheckedKeys) }}</span>
            <FontAwesomeIcon v-if="node.children?.length" :icon="isPermExpanded(node.id) ? 'chevron-down' : 'chevron-right'" class="us-perm-expand-icon" />
          </div>
          <div v-if="node.children?.length && isPermExpanded(node.id)" class="us-perm-group-body">
            <div v-for="child in node.children" :key="child.id" class="us-perm-item" @click="togglePermNode(child.id)">
              <UiCheckbox :checked="isPermChecked(child.id)" @update:checked="togglePermNode(child.id)" @click.stop />
              <span class="us-perm-item-name">{{ child.name }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <button class="us-action-btn" @click="permDialogVisible = false" aria-label="取消">取消</button>
      <button class="us-action-btn us-action-primary" :disabled="permSubmitting" @click="handleSavePermission" :aria-label="permSubmitting ? '保存中…' : '保存'">
        {{ permSubmitting ? '保存中…' : '保存' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * UserPermissionDialog.vue — 权限分配弹窗
 *
 * 从 UserView.vue 拆出：按模块分组展示权限树，支持全选/级联选择。
 * 分组数据、勾选/展开状态与级联逻辑由父组件（useUserManagement）经 props 传入。
 */
import UiDialog from '@/components/ui/UiDialog.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import type { PermissionItem } from '@/types'

defineProps<{
  /** 权限分配目标用户名 */
  permTargetName: string
  /** 按模块分组的权限树 */
  permissionSections: { key: string; name: string; items: PermissionItem[] }[]
  /** 已勾选权限 id 列表 */
  permCheckedKeys: number[]
  /** 是否全选 */
  permIsAllChecked: boolean
  /** 保存进行中 */
  permSubmitting: boolean
  /** 判断权限节点是否展开 */
  isPermExpanded: (id: number) => boolean
  /** 切换展开/折叠 */
  togglePermExpand: (id: number) => void
  /** 判断是否已勾选 */
  isPermChecked: (id: number) => boolean
  /** 切换勾选（父子级联） */
  togglePermNode: (id: number) => void
  /** 子项选中计数文本（如 "2/5"） */
  getPermChildCount: (node: PermissionItem, checked: number[]) => string
  /** 全选/取消全选 */
  toggleAllPerms: () => void
  /** 保存权限分配 */
  handleSavePermission: () => void
}>()

/** 弹窗开关（父组件 v-model:open） */
const permDialogVisible = defineModel<boolean>('open', { default: false })
</script>

<style scoped>
/* ===== Permission Dialog ===== */
.us-perm-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border-light, #e8ecf1);
}
.us-perm-user {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.us-perm-toggle-all {
  padding: 5px 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 7px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease;
}
.us-perm-toggle-all:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
}
.us-perm-tree {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.us-perm-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.us-perm-section-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0 4px;
}
.us-perm-group {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  flex-shrink: 0;
  transition: border-color 0.2s ease;
}
.us-perm-group:hover {
  border-color: var(--color-primary-200);
}
.us-perm-group-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--color-surface, #f8fafc);
  cursor: pointer;
  transition: background 0.2s ease;
  border-top-left-radius: 9px;
  border-top-right-radius: 9px;
}
.us-perm-group:not(:has(.us-perm-group-body)) .us-perm-group-header {
  border-radius: 9px;
}
.us-perm-group-header:hover {
  background: var(--color-primary-50);
}
.us-perm-group-name {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  flex: 1;
  min-width: 0;
}
.us-perm-group-icon {
  font-size: 14px;
  color: var(--color-primary-500);
  width: 18px;
  text-align: center;
  flex-shrink: 0;
}
.us-perm-group-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  background: white;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  flex-shrink: 0;
}
.us-perm-expand-icon {
  font-size: 11px;
  color: var(--color-text-muted);
  flex-shrink: 0;
  transition: transform 0.2s ease;
}
.us-perm-group-body {
  padding: 4px 14px 8px 46px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.us-perm-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.2s ease;
}
.us-perm-item:hover {
  background: var(--color-primary-50);
}
.us-perm-item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text);
}

/* Action Buttons */
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
.us-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>

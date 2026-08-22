<template>
  <!-- 权限分配弹窗 -->
  <UiDialog :open="permDialogVisible" title="分配权限" max-width-class="max-w-[680px]" @update:open="permDialogVisible = $event">
    <div class="us-perm-header">
      <div class="us-perm-user">
        <span class="us-perm-user-label">目标用户</span>
        <span class="us-perm-user-name">{{ permTargetName }}</span>
      </div>
      <button class="us-perm-toggle-all" :aria-label="permIsAllChecked ? '取消全选' : '全选'" @click="toggleAllPerms">
        {{ permIsAllChecked ? '取消全选' : '全选' }}
      </button>
    </div>
    <div class="us-perm-tree">
      <!-- section 可折叠（与左侧导航栏交互/样式统一） -->
      <div v-for="sec in permissionSections" :key="sec.key" class="us-perm-section">
        <button
          type="button"
          class="us-perm-section-header"
          :class="{ open: isSectionOpen(sec.key) }"
          :aria-expanded="isSectionOpen(sec.key)"
          @click="toggleSection(sec.key)"
        >
          <span class="us-perm-section-title">{{ sec.name }}</span>
          <span class="us-perm-section-count" :class="{ 'all-checked': isSectionAllChecked(sec) }">{{ getSectionCount(sec) }}</span>
          <span class="us-perm-section-chevron" aria-hidden="true" />
        </button>
        <div v-show="isSectionOpen(sec.key)" class="us-perm-section-body">
          <!-- 一级权限项 -->
          <div v-for="node in sec.items" :key="node.id" class="us-perm-group">
            <div
              class="us-perm-group-header"
              :class="{ 'has-children': node.children?.length }"
              @click="node.children?.length ? togglePermExpand(node.id) : togglePermNode(node.id)"
            >
              <UiCheckbox :checked="isPermChecked(node.id)" @update:checked="togglePermNode(node.id)" @click.stop />
              <span class="us-perm-group-name">
                <FontAwesomeIcon v-if="node.icon" :icon="node.icon.replace('fa-', '')" class="us-perm-group-icon" />
                {{ node.name }}
              </span>
              <span v-if="node.children?.length" class="us-perm-group-count">{{ getPermChildCount(node, permCheckedKeys) }}</span>
              <FontAwesomeIcon v-if="node.children?.length" :icon="isPermExpanded(node.id) ? 'chevron-down' : 'chevron-right'" class="us-perm-expand-icon" />
            </div>
            <!-- 二级子权限 -->
            <div v-if="node.children?.length && isPermExpanded(node.id)" class="us-perm-group-body">
              <div v-for="child in node.children" :key="child.id" class="us-perm-item" @click="togglePermNode(child.id)">
                <UiCheckbox :checked="isPermChecked(child.id)" @update:checked="togglePermNode(child.id)" @click.stop />
                <span class="us-perm-item-name">{{ child.name }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <template #footer>
      <button class="us-action-btn" aria-label="取消" @click="permDialogVisible = false">取消</button>
      <button class="us-action-btn us-action-primary" :disabled="permSubmitting" :aria-label="permSubmitting ? '保存中…' : '保存'" @click="handleSavePermission">
        {{ permSubmitting ? '保存中…' : '保存' }}
      </button>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
/**
 * UserPermissionDialog.vue — 权限分配弹窗
 *
 * UI 与左侧导航栏统一：section 采用可折叠按钮（相同样式/交互），
 * section 顺序/命名由父组件（useUserManagement）以导航栏为权威源传入。
 * 勾选/展开状态与级联逻辑由父组件经 props 传入；section 折叠状态本组件自管。
 */
import { ref, watch } from 'vue'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import type { PermissionItem } from '@/types'

type PermissionSection = { key: string; name: string; items: PermissionItem[] }

const props = defineProps<{
  /** 权限分配目标用户名 */
  permTargetName: string
  /** 按模块分组的权限树（section 顺序/命名与导航栏一致） */
  permissionSections: PermissionSection[]
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

// ==================== section 折叠状态（与导航栏交互统一） ====================
/** 已展开的 section key 集合 */
const openSections = ref<Set<string>>(new Set())

/** 首次加载时默认展开所有 section，方便用户查看 */
watch(
  () => props.permissionSections,
  (sections) => {
    if (openSections.value.size === 0 && sections.length > 0) {
      openSections.value = new Set(sections.map((s) => s.key))
    }
  },
  { immediate: true },
)

/** 判断 section 是否展开 */
function isSectionOpen(key: string): boolean {
  return openSections.value.has(key)
}

/** 切换 section 展开/折叠 */
function toggleSection(key: string) {
  const s = openSections.value
  if (s.has(key)) s.delete(key)
  else s.add(key)
}

/** 收集 section 下所有权限 id（含子权限） */
function collectSectionIds(sec: PermissionSection): number[] {
  const ids: number[] = []
  for (const node of sec.items) {
    ids.push(node.id)
    for (const c of node.children ?? []) ids.push(c.id)
  }
  return ids
}

/** 获取 section 已选/总数文本（如 "3/8"） */
function getSectionCount(sec: PermissionSection): string {
  const allIds = collectSectionIds(sec)
  const checked = allIds.filter((id) => props.permCheckedKeys.includes(id)).length
  return `${checked}/${allIds.length}`
}

/** 判断 section 是否全部选中 */
function isSectionAllChecked(sec: PermissionSection): boolean {
  const allIds = collectSectionIds(sec)
  return allIds.length > 0 && allIds.every((id) => props.permCheckedKeys.includes(id))
}
</script>

<style scoped>
/* ===== Permission Dialog ===== */
.us-perm-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border-light, #e8ecf1);
}
.us-perm-user {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.us-perm-user-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}
.us-perm-user-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}
.us-perm-toggle-all {
  padding: 6px 14px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease;
}
.us-perm-toggle-all:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.us-perm-tree {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 60vh;
  overflow-y: auto;
  padding-right: 4px;
}
.us-perm-tree::-webkit-scrollbar {
  width: 6px;
}
.us-perm-tree::-webkit-scrollbar-thumb {
  background: var(--color-border-light, #e2e8f0);
  border-radius: 3px;
}

/* ===== Section 可折叠标题（与左侧导航栏样式统一） ===== */
.us-perm-section {
  display: flex;
  flex-direction: column;
}
.us-perm-section-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  margin-bottom: 4px;
  border-radius: 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
  font-weight: 700;
  font-size: 14px;
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease, background 0.2s ease;
}
.us-perm-section-header:hover {
  color: var(--color-primary-600);
  border-color: var(--color-primary-200);
  background: var(--color-primary-50);
}
.us-perm-section-header.open {
  color: var(--color-primary-700);
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}
.us-perm-section-title {
  flex: 1;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.us-perm-section-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  background: white;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  flex-shrink: 0;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}
.us-perm-section-count.all-checked {
  background: var(--color-primary-500);
  color: white;
  border-color: var(--color-primary-500);
}
.us-perm-section-chevron {
  flex-shrink: 0;
  width: 7px;
  height: 7px;
  margin-right: 2px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(-45deg);
  transition: transform 0.25s ease;
}
.us-perm-section-header.open .us-perm-section-chevron {
  transform: rotate(45deg);
}
.us-perm-section-body {
  padding-left: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* ===== 一级权限组 ===== */
.us-perm-group {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  flex-shrink: 0;
  transition: border-color 0.2s ease;
  background: white;
}
.us-perm-group:hover {
  border-color: var(--color-primary-200);
}
.us-perm-group-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  background: var(--color-surface, #f8fafc);
  cursor: pointer;
  transition: background 0.2s ease;
  border-top-left-radius: 9px;
  border-top-right-radius: 9px;
}
.us-perm-group:not(.has-children) .us-perm-group-header,
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

/* ===== 二级子权限 ===== */
.us-perm-group-body {
  padding: 4px 12px 8px 44px;
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

/* ===== Action Buttons ===== */
.us-action-btn {
  padding: 6px 14px;
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

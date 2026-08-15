<template>
  <div class="us-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部 -->

      <!-- 双栏主体 -->
      <div class="us-body">
        <!-- 左栏：添加用户 -->
        <div class="us-col">
          <div class="us-col-title"><FontAwesomeIcon icon="user-plus" aria-hidden="true" /> 添加新用户</div>
          <div class="us-col-scroll">
            <form @submit.prevent="handleAdd" class="us-form">
              <div class="us-form-group">
                <label>用户名 <span class="us-required">*</span></label>
                <input v-model="form.username" class="us-input" placeholder="请输入用户名" />
              </div>
              <div class="us-form-group">
                <label>密码 <span class="us-required">*</span></label>
                <div class="us-input-wrapper">
                  <input v-model="form.password" :type="showPwd1 ? 'text' : 'password'" class="us-input" placeholder="至少6位" />
                  <button type="button" class="us-pwd-toggle" @click="showPwd1 = !showPwd1" aria-label="查看">
                    <FontAwesomeIcon :icon="showPwd1 ? 'eye-slash' : 'eye'" aria-hidden="true" />
                  </button>
                </div>
              </div>
              <div class="us-form-group us-form-group-row">
                <UiCheckbox :checked="form.isSuper" @update:checked="form.isSuper = $event" />
                <label class="us-checkbox-label" @click="form.isSuper = !form.isSuper">超级管理员</label>
              </div>
              <div class="us-form-group">
                <label>工厂</label>
                <select v-model="form.factory" class="us-input" aria-label="工厂">
                  <option value="">无（跨厂管理员）</option>
                  <option v-for="f in FACTORY_OPTIONS" :key="f" :value="f">{{ f }}</option>
                </select>
              </div>
              <p v-if="formError" class="us-form-error">{{ formError }}</p>
              <button type="submit" class="us-submit-btn" :disabled="submitting">
                {{ submitting ? '添加中…' : '添加用户' }}
              </button>
            </form>
          </div>
        </div>

        <!-- 右栏：用户列表 -->
        <div class="us-col">
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
                  <button class="us-action-btn us-action-primary" @click="openPermissionDialog(row as UserRow)">权限</button>
                  <button class="us-action-btn us-action-primary" @click="openEditDialog(row as UserRow)">编辑</button>
                  <button class="us-action-btn us-action-primary" :disabled="actionId === (row as UserRow).id" @click="handleToggle(row as UserRow)">
                    {{ (row as UserRow).status !== false ? '禁用' : '启用' }}
                  </button>
                  <button class="us-action-btn us-action-danger" :disabled="actionId === (row as UserRow).id || (row as UserRow).is_super" @click="handleDelete(row as UserRow)">
                    删除
                  </button>
                </div>
              </template>
            </UiDataTable>
          </div>
        </div>
      </div>
    </div>

    <!-- 编辑用户工厂弹窗 -->
    <UiDialog :open="editDialogVisible" title="编辑用户" max-width-class="max-w-[480px]" @update:open="editDialogVisible = $event">
      <div class="us-edit-form">
        <div class="us-edit-username">用户名：{{ editTargetName }}</div>
        <div class="us-form-group">
          <label>工厂</label>
          <select v-model="editForm.factory" class="us-input" aria-label="工厂">
            <option value="">无（跨厂管理员）</option>
            <option v-for="f in FACTORY_OPTIONS" :key="f" :value="f">{{ f }}</option>
          </select>
        </div>
      </div>
      <template #footer>
        <button class="us-action-btn" @click="editDialogVisible = false">取消</button>
        <button class="us-action-btn us-action-primary" :disabled="editSubmitting" @click="handleSaveEdit">
          {{ editSubmitting ? '保存中…' : '保存' }}
        </button>
      </template>
    </UiDialog>

    <!-- 权限分配弹窗 -->
    <UiDialog :open="permDialogVisible" title="分配权限" max-width-class="max-w-[640px]" @update:open="permDialogVisible = $event">
      <div class="us-perm-header">
        <div class="us-perm-user">{{ permTargetName }}</div>
        <button class="us-perm-toggle-all" @click="toggleAllPerms">{{ permIsAllChecked ? '取消全选' : '全选' }}</button>
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
        <button class="us-action-btn" @click="permDialogVisible = false">取消</button>
        <button class="us-action-btn us-action-primary" :disabled="permSubmitting" @click="handleSavePermission">
          {{ permSubmitting ? '保存中…' : '保存' }}
        </button>
      </template>
    </UiDialog>
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
 */
import { ref, reactive, computed } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { userApi, permissionApi } from '@/api'
import type { PermissionItem } from '@/types'
import UiDialog from '@/components/ui/UiDialog.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import { showToast } from '@/composables/useToast'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { formatDate } from '@/utils/format'

/** 用户列表行数据 */
interface UserRow {
  id: number
  username: string
  is_super?: boolean
  status?: boolean
  factory?: string | null
  create_time?: string
}

/** 工厂下拉选项（与后端 VALID_FACTORIES 保持一致） */
const FACTORY_OPTIONS = ['东莞', '湖北'] as const

/** 从错误对象中提取后端返回的 detail 信息 */
function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((d: { msg?: string }) => d.msg).join('; ') || fallback
  }
  if (typeof detail === 'string') return detail
  return fallback
}

const actionId = ref<number | ''>(0)
const formError = ref('')
const showPwd1 = ref(false)
const queryClient = useQueryClient()
const confirmDialog = useConfirmDialog()

const currentPage = ref(1)
const perPage = ref(15)

/** 用户列表查询 */
const { data: result, isLoading } = useQuery({
  queryKey: ['users-list', () => currentPage.value, () => perPage.value],
  queryFn: () => userApi.list({ page: currentPage.value, per_page: perPage.value }),
  staleTime: 30_000,
  gcTime: 60_000,
})
/** 当前页用户列表 */
const users = computed(() => result.value?.users ?? [])
/** 用户总数 */
const totalItems = computed(() => result.value?.total ?? users.value.length)

/** UiDataTable 列定义 */
const userColumns: TableColumn[] = [
  { field: 'username', header: '用户名', align: 'left' },
  { field: 'is_super', header: '角色', align: 'center' },
  { field: 'factory', header: '工厂', align: 'center' },
  { field: 'status', header: '状态', align: 'center' },
  { field: 'create_time', header: '创建时间', align: 'left' },
  { field: 'actions', header: '操作', align: 'right' },
]

/** UiDataTable 分页变化处理 */
function onPageChange(event: { page: number; rows: number }) {
  currentPage.value = event.page + 1
  perPage.value = event.rows
}

// 添加用户
const submitting = ref(false)
const form = reactive({ username: '', password: '', isSuper: false, factory: '' })

/** 提交添加用户表单 */
async function handleAdd() {
  formError.value = ''
  if (!form.username) {
    formError.value = '请输入用户名'
    return
  }
  if (!form.password) {
    formError.value = '请输入密码'
    return
  }
  if (form.password.length < 6) {
    formError.value = '密码至少6位'
    return
  }
  submitting.value = true
  try {
    await userApi.create({
      username: form.username,
      password: form.password,
      is_super: form.isSuper,
      factory: form.factory || null,
    })
    showToast('添加成功', 'success')
    Object.assign(form, { username: '', password: '', isSuper: false, factory: '' })
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '添加失败'), 'error')
  } finally {
    submitting.value = false
  }
}

/** 切换用户启用/禁用状态 */
async function handleToggle(row: UserRow) {
  actionId.value = row.id
  try {
    await userApi.toggle(row.id)
    showToast('操作成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '操作失败'), 'error')
  } finally {
    actionId.value = 0
  }
}

/** 删除用户（带确认弹窗） */
async function handleDelete(row: UserRow) {
  if (!(await confirmDialog.confirm(`确定要删除用户"${row.username}"吗？`))) return
  actionId.value = row.id
  try {
    await userApi.delete(row.id)
    showToast('删除成功', 'success')
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '删除失败'), 'error')
  } finally {
    actionId.value = 0
  }
}

// 编辑用户工厂
const editDialogVisible = ref(false)
const editSubmitting = ref(false)
const editTargetId = ref(0)
const editTargetName = ref('')
const editForm = reactive<{ factory: string }>({ factory: '' })

/** 打开编辑用户弹窗，预填当前工厂值 */
function openEditDialog(row: UserRow) {
  editTargetId.value = row.id
  editTargetName.value = row.username
  editForm.factory = row.factory || ''
  editDialogVisible.value = true
}

/** 保存用户工厂编辑 */
async function handleSaveEdit() {
  editSubmitting.value = true
  try {
    await userApi.update(editTargetId.value, { factory: editForm.factory || null })
    showToast('保存成功', 'success')
    editDialogVisible.value = false
    queryClient.invalidateQueries({ queryKey: ['users-list'] })
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '保存失败'), 'error')
  } finally {
    editSubmitting.value = false
  }
}

// 权限分配
const permDialogVisible = ref(false)
const permSubmitting = ref(false)
const permissionTree = ref<PermissionItem[]>([])
const permCheckedKeys = ref<number[]>([])
const permExpandedKeys = ref<Set<number>>(new Set())
const permTargetUserId = ref(0)
const permTargetName = ref('')

/** 权限模块分区排序优先级 */
const sectionOrder = ['purchase', 'purchase_tools', 'core', 'data', 'system']

/** 按模块分区对权限树进行分组 */
const permissionSections = computed(() => {
  const map = new Map<string, { key: string; name: string; items: PermissionItem[] }>()
  for (const node of permissionTree.value) {
    const secKey = node.section || 'other'
    const secName = node.section_name || secKey
    if (!map.has(secKey)) map.set(secKey, { key: secKey, name: secName, items: [] })
    map.get(secKey)!.items.push(node)
  }
  const sections = [...map.values()]
  sections.sort((a, b) => {
    const ai = sectionOrder.indexOf(a.key)
    const bi = sectionOrder.indexOf(b.key)
    if (ai !== -1 && bi !== -1) return ai - bi
    if (ai !== -1) return -1
    if (bi !== -1) return 1
    return a.key.localeCompare(b.key)
  })
  return sections
})

/** 判断权限节点是否展开 */
function isPermExpanded(id: number): boolean {
  return permExpandedKeys.value.has(id)
}

/** 切换权限节点的展开/折叠状态 */
function togglePermExpand(id: number) {
  const s = permExpandedKeys.value
  if (s.has(id)) s.delete(id)
  else s.add(id)
}

/** 判断权限节点是否已选中 */
function isPermChecked(id: number): boolean {
  return permCheckedKeys.value.includes(id)
}

/** 切换权限节点的选中状态，支持父子级联 */
function togglePermNode(id: number) {
  const node = permissionTree.value.find((n) => n.id === id)
  if (node && node.children?.length) {
    // Toggle parent with children: cascade to all children
    const childIds = node.children.map((c) => c.id)
    const allChecked = childIds.every((cid) => permCheckedKeys.value.includes(cid))
    if (allChecked) {
      // Uncheck parent + all children
      permCheckedKeys.value = permCheckedKeys.value.filter((k) => k !== id && !childIds.includes(k))
    } else {
      // Check parent + all children
      const toAdd = [id, ...childIds].filter((k) => !permCheckedKeys.value.includes(k))
      permCheckedKeys.value.push(...toAdd)
    }
  } else {
    // Toggle child or parent without children: simple toggle
    const idx = permCheckedKeys.value.indexOf(id)
    if (idx >= 0) {
      permCheckedKeys.value.splice(idx, 1)
      // Uncheck parent if no siblings checked
      for (const parent of permissionTree.value) {
        if (parent.children?.some((c) => c.id === id)) {
          const anyChildChecked = parent.children.some((c) => permCheckedKeys.value.includes(c.id))
          if (!anyChildChecked) {
            const pidx = permCheckedKeys.value.indexOf(parent.id)
            if (pidx >= 0) permCheckedKeys.value.splice(pidx, 1)
          }
          break
        }
      }
    } else {
      permCheckedKeys.value.push(id)
      // Check parent if all siblings checked
      for (const parent of permissionTree.value) {
        if (parent.children?.some((c) => c.id === id)) {
          const allChildrenChecked = parent.children.every((c) => permCheckedKeys.value.includes(c.id))
          if (allChildrenChecked) {
            if (!permCheckedKeys.value.includes(parent.id)) {
              permCheckedKeys.value.push(parent.id)
            }
          }
          break
        }
      }
    }
  }
}

/** 获取权限节点子项的选中计数文本（如 "2/5"） */
function getPermChildCount(node: PermissionItem, checked: number[]): string {
  if (!node.children?.length) return ''
  const total = node.children.length
  const checkedCount = node.children.filter((c) => checked.includes(c.id)).length
  return `${checkedCount}/${total}`
}

/** 是否所有权限节点均已选中 */
const permIsAllChecked = computed(() => {
  const allIds: number[] = []
  for (const node of permissionTree.value) {
    allIds.push(node.id)
    for (const c of node.children ?? []) allIds.push(c.id)
  }
  return allIds.length > 0 && allIds.every((id: number) => permCheckedKeys.value.includes(id))
})

/** 全选/取消全选所有权限 */
function toggleAllPerms() {
  const allIds: number[] = []
  for (const node of permissionTree.value) {
    allIds.push(node.id)
    for (const c of node.children ?? []) allIds.push(c.id)
  }
  if (permIsAllChecked.value) {
    permCheckedKeys.value = []
  } else {
    permCheckedKeys.value = [...allIds]
  }
}

/** 打开权限分配弹窗，加载权限树和用户已有权限 */
async function openPermissionDialog(row: UserRow) {
  permTargetUserId.value = row.id
  permTargetName.value = row.username
  try {
    const [permRes, userPermRes] = await Promise.all([
      permissionApi.tree(),
      userApi.getPermission(row.id),
    ])
    permissionTree.value = permRes
    permCheckedKeys.value = userPermRes.user_permission_ids
    permExpandedKeys.value = new Set()
    permDialogVisible.value = true
  } catch {
    showToast('加载权限数据失败', 'error')
  }
}

/** 保存用户权限分配 */
async function handleSavePermission() {
  permSubmitting.value = true
  try {
    await userApi.savePermission(permTargetUserId.value, permCheckedKeys.value)
    showToast('权限保存成功', 'success')
    permDialogVisible.value = false
  } catch (err: unknown) {
    showToast(extractErrorMessage(err, '保存失败'), 'error')
  } finally {
    permSubmitting.value = false
  }
}
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
.us-col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}
.us-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}
.us-col-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 16px 20px;
}

/* Form */
.us-form {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.us-form-group {
  margin-bottom: 14px;
}
.us-form-group-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.us-checkbox-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  cursor: pointer;
  user-select: none;
}
.us-form-group label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.us-required {
  color: var(--color-danger-500);
}
.us-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.us-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.us-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.us-input-wrapper {
  position: relative;
}
.us-pwd-toggle {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  color: var(--color-text-muted);
  padding: 4px;
  transition: color 0.2s ease;
}
.us-pwd-toggle:hover {
  color: var(--color-text-secondary);
}
.us-form-error {
  color: var(--color-danger-500);
  font-size: 12px;
  margin-bottom: 8px;
}
.us-submit-btn {
  width: 100%;
  padding: 10px 16px;
  border: none;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.us-submit-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 148, 191, 0.3);
}
.us-submit-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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

/* Edit Dialog */
.us-edit-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.us-edit-username {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
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

/* ===== Permission Dialog ===== */
.us-perm-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
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
</style>

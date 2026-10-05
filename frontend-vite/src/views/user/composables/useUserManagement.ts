/**
 * useUserManagement.ts — 用户管理页面逻辑
 *
 * 从 UserView.vue 下沉的逻辑：用户列表查询/分页、启用禁用切换、删除（确认弹窗）、
 * 编辑用户弹窗状态与保存、权限分配弹窗的分组/级联选择/保存。
 */
import { ref, computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { userApi, permissionApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { PermissionItem } from '@/types'
import { showToast } from '@/composables/useToast'
import { useApiMutation } from '@/composables/useApiMutation'
import { useConfirmDialog } from '@/composables/useConfirmDialog'

/** 用户列表行数据 */
export interface UserRow {
  id: number
  username: string
  is_super?: boolean
  status?: boolean
  factory?: string | null
  create_time?: string
}

/** 工厂下拉选项（与后端 VALID_FACTORIES 保持一致） */
export const FACTORY_OPTIONS = ['东莞', '湖北'] as const

/** 密码最小长度（与后端 utils/password_validator.PasswordValidator.MIN_LENGTH 保持一致） */
export const PASSWORD_MIN_LENGTH = 6

/**
 * 权限分配弹窗「其他操作权限」分区的固定 key。
 * 导航栏不显示的权限（is_nav=false 的操作权限、已下线项等）统一收进该分区，默认收起。
 */
export const EXTRAS_SECTION_KEY = '__extras__'

/** 导航分区（仅需 items[].permission 与权限树按 code 匹配） */
export interface NavSectionLike {
  key?: string
  title: string
  items: { permission?: string }[]
}

/** 权限分配弹窗的一个分区 */
export interface PermissionSection {
  key: string
  name: string
  items: PermissionItem[]
}

/**
 * 按导航栏分组权限树（纯函数，便于单测）。
 *
 * 以 navSections（后端导航数据，已剔除下线项）为**权威源**：分区顺序 / 命名 /
 * 条目全部照抄导航栏，权限树按 code 匹配进来，从而保证「分配权限」界面与左侧
 * 导航栏一一对应、改一处两边同步。
 *
 * 匹配不上的顶层权限（is_nav=false 的操作权限、已下线项、无 section 项）收进
 * 末尾的「其他操作权限」区，默认收起，不干扰主视图。
 */
export function buildPermissionSections(
  permissionTree: readonly PermissionItem[],
  navSections: readonly NavSectionLike[],
): PermissionSection[] {
  const byCode = new Map<string, PermissionItem>()
  for (const node of permissionTree) byCode.set(node.code, node)

  const result: PermissionSection[] = []
  const usedIds = new Set<number>()

  for (const navSec of navSections) {
    const items: PermissionItem[] = []
    for (const navItem of navSec.items) {
      const node = navItem.permission ? byCode.get(navItem.permission) : undefined
      if (node && !usedIds.has(node.id)) {
        items.push(node)
        usedIds.add(node.id)
      }
    }
    if (items.length > 0) {
      result.push({ key: navSec.key || navSec.title, name: navSec.title, items })
    }
  }

  const extras = permissionTree.filter((n) => !usedIds.has(n.id))
  if (extras.length > 0) {
    result.push({ key: EXTRAS_SECTION_KEY, name: '其他操作权限', items: extras })
  }

  return result
}

/** 从错误对象中提取后端返回的 detail 信息 */
export function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((d: { msg?: string }) => d.msg).join('; ') || fallback
  }
  if (typeof detail === 'string') return detail
  return fallback
}

/** 用户管理：列表 + 行操作 + 编辑弹窗 + 权限弹窗 */
export function useUserManagement() {
  const actionId = ref<number | ''>(0)
  const confirmDialog = useConfirmDialog()
  const authStore = useAuthStore()

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

  /** UiDataTable 分页变化处理 */
  function onPageChange(event: { page: number; rows: number }) {
    currentPage.value = event.page + 1
    perPage.value = event.rows
  }

  /** 切换用户启用/禁用状态 */
  const toggleMutation = useApiMutation((id: number) => userApi.toggle(id), {
    invalidateKeys: ['users-list'],
    successMsg: '操作成功',
    errorMsg: '操作失败',
  })

  async function handleToggle(row: UserRow) {
    actionId.value = row.id
    await toggleMutation.run(row.id)
    actionId.value = 0
  }

  /** 删除用户（带确认弹窗） */
  const deleteMutation = useApiMutation((id: number) => userApi.delete(id), {
    invalidateKeys: ['users-list'],
    successMsg: '删除成功',
    errorMsg: '删除失败',
  })

  async function handleDelete(row: UserRow) {
    if (!(await confirmDialog.confirm(`确定要删除用户"${row.username}"吗？`))) return
    actionId.value = row.id
    await deleteMutation.run(row.id)
    actionId.value = 0
  }

  // ==================== 编辑用户工厂弹窗 ====================
  const editDialogVisible = ref(false)
  /** 编辑目标用户 id（保存时使用） */
  const editTargetId = ref(0)
  /** 编辑目标用户名（弹窗内展示） */
  const editTargetName = ref('')
  /** 打开弹窗时的工厂初值（弹窗内同步到输入框） */
  const editInitialFactory = ref('')

  /** 打开编辑用户弹窗，预填当前工厂值 */
  function openEditDialog(row: UserRow) {
    editTargetId.value = row.id
    editTargetName.value = row.username
    editInitialFactory.value = row.factory || ''
    editDialogVisible.value = true
  }

  // ==================== 权限分配弹窗 ====================
  const permDialogVisible = ref(false)
  const permissionTree = ref<PermissionItem[]>([])
  const permCheckedKeys = ref<number[]>([])
  const permExpandedKeys = ref<Set<number>>(new Set())
  const permTargetUserId = ref(0)
  const permTargetName = ref('')

  /** 按导航栏分组权限树（顺序/命名/条目照抄导航，非导航权限收进「其他操作权限」区） */
  const permissionSections = computed(() =>
    buildPermissionSections(permissionTree.value, authStore.navSections),
  )

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
      // 确保导航栏 section 数据已就绪且包含 key 字段（作为权限分区的权威源）
      // 若 navSections 为空或缺少 key 字段（如 HMR 前的旧数据残留），重新加载
      const needReloadNav = authStore.navSections.length === 0 || !authStore.navSections[0]?.key
      if (needReloadNav) {
        await authStore.fetchNavSections().catch(() => {})
      }
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
  const savePermMutation = useApiMutation(
    (target: { userId: number; keys: number[] }) => userApi.savePermission(target.userId, target.keys),
    {
      successMsg: '权限保存成功',
      errorMsg: '保存失败',
      onSuccess: () => {
        // 权限变更可能影响导航栏结构，异步刷新以保持同步
        authStore.fetchNavSections().catch(() => {})
        permDialogVisible.value = false
      },
    },
  )
  /** 权限弹窗提交中（映射包装器的 in-flight 态） */
  const permSubmitting = savePermMutation.isSaving

  async function handleSavePermission() {
    // 失败由包装器统一 toast（'保存失败'兜底），返回 undefined 即未成功
    await savePermMutation.run({ userId: permTargetUserId.value, keys: permCheckedKeys.value })
  }

  return {
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
  }
}

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
  department?: string | null
  create_time?: string
}

/** 工厂下拉选项（与后端 VALID_FACTORIES 保持一致） */
export const FACTORY_OPTIONS = ['东莞', '湖北'] as const

/** 部门下拉选项（与后端 VALID_DEPARTMENTS 保持一致） */
export const DEPARTMENT_OPTIONS = ['生产部', '仓库', '业务部', '采购部'] as const

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

/** 一组权限节点的勾选状态：全选 / 半选 / 未选 */
export type PermissionCheckState = 'all' | 'partial' | 'none'

/** 收集单个模块（顶层权限）连同其子权限的 id */
export function collectModuleIds(node: PermissionItem): number[] {
  const ids = [node.id]
  for (const c of node.children ?? []) ids.push(c.id)
  return ids
}

/** 收集分区下所有权限 id（含子权限） */
export function collectSectionIds(sec: PermissionSection): number[] {
  return sec.items.flatMap(collectModuleIds)
}

/** 统计 ids 中已被勾选的数量 */
export function countChecked(ids: readonly number[], checked: readonly number[]): number {
  return ids.filter((id) => checked.includes(id)).length
}

/** 判定一组权限 id 的勾选状态（空集合按「未选」处理，避免误显示成全选） */
export function getPermissionCheckState(
  ids: readonly number[],
  checked: readonly number[],
): PermissionCheckState {
  if (ids.length === 0) return 'none'
  const n = countChecked(ids, checked)
  if (n === 0) return 'none'
  if (n === ids.length) return 'all'
  return 'partial'
}

/**
 * 按关键词过滤分区：命中模块名/code、模块下任一子权限名/code，或分区名本身。
 * 空白查询原样返回（浅拷贝，避免调用方误改入参）。
 */
export function filterPermissionSections(
  sections: readonly PermissionSection[],
  query: string,
): PermissionSection[] {
  const q = query.trim().toLowerCase()
  if (!q) return [...sections]
  const result: PermissionSection[] = []
  for (const sec of sections) {
    if (sec.name.toLowerCase().includes(q)) {
      result.push(sec)
      continue
    }
    const items = sec.items.filter((node) => {
      if (node.name.toLowerCase().includes(q) || node.code.toLowerCase().includes(q)) return true
      return (node.children ?? []).some(
        (c) => c.name.toLowerCase().includes(q) || c.code.toLowerCase().includes(q),
      )
    })
    if (items.length > 0) result.push({ ...sec, items })
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

  // ==================== 编辑用户弹窗（工厂/部门） ====================
  const editDialogVisible = ref(false)
  /** 编辑目标用户 id（保存时使用） */
  const editTargetId = ref(0)
  /** 编辑目标用户名（弹窗内展示） */
  const editTargetName = ref('')
  /** 打开弹窗时的工厂初值（弹窗内同步到输入框） */
  const editInitialFactory = ref('')
  /** 打开弹窗时的部门初值（弹窗内同步到输入框） */
  const editInitialDepartment = ref('')

  /** 打开编辑用户弹窗，预填当前工厂/部门值 */
  function openEditDialog(row: UserRow) {
    editTargetId.value = row.id
    editTargetName.value = row.username
    editInitialFactory.value = row.factory || ''
    editInitialDepartment.value = row.department || ''
    editDialogVisible.value = true
  }

  // ==================== 权限分配弹窗 ====================
  const permDialogVisible = ref(false)
  const permissionTree = ref<PermissionItem[]>([])
  const permCheckedKeys = ref<number[]>([])
  const permTargetUserId = ref(0)
  const permTargetName = ref('')

  /** 按导航栏分组权限树（顺序/命名/条目照抄导航，非导航权限收进「其他操作权限」区） */
  const permissionSections = computed(() =>
    buildPermissionSections(permissionTree.value, authStore.navSections),
  )

  /** 全部权限 id（含子权限） */
  const allPermissionIds = computed(() => permissionTree.value.flatMap(collectModuleIds))

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
        // 取消子项不连带取消父项（2026-10-07）：父项本身是「查看」授权，
        // 逐个取消子项后应停留在「仅查看」——原先取消最后一个子项会连父项
        // 一起取消，「只给看不给改」的授权永远配不出来。
      } else {
        permCheckedKeys.value.push(id)
        // 子项蕴含父项（2026-10-07）：勾任一子项必须带上父项。原先仅当兄弟
        // 全勾才反推父项，会出现「有 编辑/删除 却没有 订单列表」的孤儿授权
        // ——操作按钮无处展示，权限组合无意义。
        for (const parent of permissionTree.value) {
          if (parent.children?.some((c) => c.id === id)) {
            if (!permCheckedKeys.value.includes(parent.id)) {
              permCheckedKeys.value.push(parent.id)
            }
            break
          }
        }
      }
    }
  }

  /** 是否所有权限节点均已选中 */
  const permIsAllChecked = computed(
    () =>
      allPermissionIds.value.length > 0 &&
      countChecked(allPermissionIds.value, permCheckedKeys.value) === allPermissionIds.value.length,
  )

  /** 全选/取消全选所有权限 */
  function toggleAllPerms() {
    permCheckedKeys.value = permIsAllChecked.value ? [] : [...allPermissionIds.value]
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
        // P1（2026-10-24）：静默吞掉会让权限分区缺 key、勾选状态错乱，必须提示
        await authStore.fetchNavSections().catch(() => {
          showToast('导航数据加载失败，权限分区可能不完整', 'warning')
        })
      }
      const [permRes, userPermRes] = await Promise.all([
        permissionApi.tree(),
        userApi.getPermission(row.id),
      ])
      permissionTree.value = permRes
      permCheckedKeys.value = userPermRes.user_permission_ids
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
        // P1（2026-10-24）：刷新失败不能静默——否则提示「保存成功」但菜单不变，
        // 管理员会重复保存或怀疑没生效。
        authStore.fetchNavSections().catch(() => {
          showToast('权限已保存，但菜单刷新失败，请手动刷新页面', 'warning')
        })
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
    editInitialDepartment,
    openEditDialog,
    permDialogVisible,
    permSubmitting,
    permCheckedKeys,
    permTargetName,
    permissionSections,
    isPermChecked,
    togglePermNode,
    permIsAllChecked,
    toggleAllPerms,
    openPermissionDialog,
    handleSavePermission,
  }
}

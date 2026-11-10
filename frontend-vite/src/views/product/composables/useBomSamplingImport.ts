import { computed, ref, type Ref } from 'vue'
import { patternRoomApi, type PartDetail, type ProjectStatus, type ProjectSummary, type RoleBrief } from '@/api/patternRoom'
import { showToast } from '@/composables/useToast'
import type { BomItem, Role } from './bomTypes'
import {
  buildSamplingImportRows,
  mapSamplingPartToBom,
  type SamplingImportRow,
  type SamplingImportSourceGroup,
} from './bomSamplingImport'

type StatusFilter = 'all' | Extract<ProjectStatus, 'in_progress' | 'completed'>

interface UseBomSamplingImportOptions {
  bomRoles: Ref<Role[]>
  supplierOptions: Ref<{ id: number; name: string }[]>
  getFabricItems: (role: Role) => BomItem[]
  addRole: (name: string) => void
  applyItem: (role: Role, item: BomItem) => void
  selectRole: (role: Role | null) => void
  showFabricTab: () => void
}

function requestErrorMessage(error: unknown, fallback: string): string {
  const status = (error as { response?: { status?: number } })?.response?.status
  if (status === 403) return '没有打样单查看权限（需要 customer_sampling_view 或 customer_sampling_manage）'
  if (status === 404) return '打样单不存在或已被删除，请重新搜索'
  return fallback
}

/** 打样单只读查询与预览；确认后仅回调 BOM 编辑态，不发起任何写请求。 */
export function useBomSamplingImport(options: UseBomSamplingImportOptions) {
  const samplingImportVisible = ref(false)
  const samplingSearchKeyword = ref('')
  const samplingProjects = ref<ProjectSummary[]>([])
  const samplingStatusFilter = ref<StatusFilter>('all')
  const samplingSearched = ref(false)
  const samplingSearching = ref(false)
  const samplingLoadingParts = ref(false)
  const samplingError = ref('')
  const samplingSelectedProjectId = ref<number | null>(null)
  const samplingImportRows = ref<SamplingImportRow[]>([])
  const samplingHasRoles = ref(true)
  const rolesCache = new Map<number, RoleBrief[]>()
  let searchSeq = 0
  let previewSeq = 0

  const samplingSelectedRows = computed(() => samplingImportRows.value.filter((row) => row.selected))
  const samplingHasConflict = computed(() => samplingImportRows.value.some((row) => row.status === 'conflict'))
  const samplingVisibleProjects = computed(() => {
    if (samplingStatusFilter.value === 'all') return samplingProjects.value
    return samplingProjects.value.filter((project) => project.status === samplingStatusFilter.value)
  })

  function openSamplingImport() {
    previewSeq += 1
    samplingImportVisible.value = true
    samplingSearchKeyword.value = ''
    samplingProjects.value = []
    samplingStatusFilter.value = 'all'
    samplingSearched.value = false
    samplingError.value = ''
    samplingSelectedProjectId.value = null
    samplingImportRows.value = []
    samplingHasRoles.value = true
    rolesCache.clear()
    // 打开即列出全部打样单，用户无需先输入产品名搜索。
    void searchSamplingProjects()
  }

  async function fetchProjectRoles(projectId: number): Promise<RoleBrief[]> {
    const cached = rolesCache.get(projectId)
    if (cached) return cached
    const response = await patternRoomApi.listRoles(projectId)
    const roles = response.items ?? []
    rolesCache.set(projectId, roles)
    return roles
  }

  async function searchSamplingProjects() {
    const keyword = samplingSearchKeyword.value.trim()
    const seq = ++searchSeq
    previewSeq += 1
    samplingSearching.value = true
    samplingError.value = ''
    samplingSearched.value = false
    samplingSelectedProjectId.value = null
    samplingImportRows.value = []
    try {
      const projects: ProjectSummary[] = []
      const seen = new Set<number>()
      let page = 1
      let total = 0
      do {
        const response = await patternRoomApi.listProjects({
          ...(keyword ? { keyword } : {}),
          status: 'all',
          page,
          per_page: 100,
        })
        let added = 0
        for (const project of response.items ?? []) {
          if (!seen.has(project.id)) {
            seen.add(project.id)
            projects.push(project)
            added += 1
          }
        }
        total = response.total ?? projects.length
        page += 1
        // 并发写入导致分页漂移时本轮可能全是重复项；没有新增就停止，避免死循环。
        if (added === 0) break
      } while (projects.length < total)
      if (seq !== searchSeq) return
      samplingProjects.value = projects
      samplingSearched.value = true
    } catch (error) {
      if (seq !== searchSeq) return
      samplingProjects.value = []
      samplingSearched.value = true
      samplingError.value = requestErrorMessage(error, '打样单加载失败，请稍后重试')
    } finally {
      if (seq === searchSeq) samplingSearching.value = false
    }
  }

  async function selectSamplingProject(project: ProjectSummary) {
    const seq = ++previewSeq
    const projectId = project.id
    samplingSelectedProjectId.value = projectId
    samplingImportRows.value = []
    samplingHasRoles.value = true
    samplingLoadingParts.value = true
    samplingError.value = ''
    try {
      const roles = await fetchProjectRoles(projectId)
      const groups: SamplingImportSourceGroup[] = await Promise.all(roles.map(async (role) => {
        const response = await patternRoomApi.getPartsByVersion(projectId, role.id, true)
        return { role, parts: (response.items ?? []) as PartDetail[] }
      }))
      if (seq !== previewSeq || samplingSelectedProjectId.value !== projectId) return
      samplingHasRoles.value = roles.length > 0
      samplingImportRows.value = buildSamplingImportRows(
        groups,
        options.bomRoles.value,
        options.getFabricItems,
      )
    } catch (error) {
      if (seq !== previewSeq) return
      samplingError.value = requestErrorMessage(error, '读取打样单最终版本部位失败，请重试')
    } finally {
      if (seq === previewSeq) samplingLoadingParts.value = false
    }
  }

  function confirmSamplingImport() {
    const rows = samplingSelectedRows.value
    if (!rows.length) {
      samplingError.value = '请至少勾选一条部位'
      return
    }
    const validSupplierIds = new Set(options.supplierOptions.value.map((supplier) => supplier.id))
    const firstRoleName = rows[0]!.sourceRoleName
    if (rows.some((row) => !row.sourceRoleName)) {
      samplingError.value = '打样单存在空角色名称，未导入任何数据'
      return
    }
    for (const row of rows) {
      let role = options.bomRoles.value.find((item) => item.name.trim() === row.sourceRoleName)
      if (!role) {
        // 复用既有新增角色入口，保证 role_key + role_name 的保存契约唯一。
        options.addRole(row.sourceRoleName)
        role = options.bomRoles.value.find((item) => item.name.trim() === row.sourceRoleName)
      }
      if (!role) {
        samplingError.value = `无法建立 BOM 角色「${row.sourceRoleName}」，未导入任何数据`
        return
      }
      const targetItems = options.getFabricItems(role)
      const existing = targetItems.find((item) => (item.part_name ?? '').trim() === row.part.part_name.trim())
      options.applyItem(role, mapSamplingPartToBom(row.part, validSupplierIds, existing))
    }
    const firstRole = options.bomRoles.value.find((role) => role.name.trim() === firstRoleName) ?? null
    options.selectRole(firstRole)
    options.showFabricTab()
    samplingImportVisible.value = false
    showToast(`已将 ${rows.length} 条部位导入 BOM 编辑态；数量均为 0，请补录后保存`, 'warning')
  }

  return {
    samplingImportVisible,
    samplingSearchKeyword,
    samplingProjects,
    samplingVisibleProjects,
    samplingStatusFilter,
    samplingSearched,
    samplingSearching,
    samplingLoadingParts,
    samplingError,
    samplingSelectedProjectId,
    samplingImportRows,
    samplingSelectedRows,
    samplingHasRoles,
    samplingHasConflict,
    openSamplingImport,
    searchSamplingProjects,
    selectSamplingProject,
    confirmSamplingImport,
  }
}

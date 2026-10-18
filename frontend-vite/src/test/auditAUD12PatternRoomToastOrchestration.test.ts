/**
 * AUD-12 补充回归：板房编排 Hook 的「假成功」缺口与 403 双弹（2026-10-18 OCR 复评）。
 *
 * 背景：AUD-12 首轮修复给 usePatternRoomPartActions/ProjectActions 的 catch 补了
 * toastActionError，但漏了三类缺口：
 *  1. roleHook.error 分支（onSetFinalVersion / onCopyPartVersion）未过 403 过滤——
 *     403 时 axios 拦截器与本处会各弹一条 toast；
 *  2. onAddRole/onRemoveRole 与 onProjectSubmitCreate/Update/confirmDeleteProject
 *     是裸 await：底层 hook（useSamplingRole/useSamplingProject）内部吞异常返回 null，
 *     调用方只判 null 之前的旧写法，失败被当成成功；
 *  3. uploadPendingImage 的 catch 直接 showToast 固定文案，同样会与拦截器双弹。
 *
 * 本测试以最小桩驱动这些编排 Hook，锁定「失败必须可见、403 不双弹」。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const mocks = vi.hoisted(() => ({
  showToast: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))
vi.mock('@/api/patternRoom', () => ({
  patternRoomApi: {
    copyPartVersion: vi.fn(),
    updatePart: vi.fn(),
    deletePart: vi.fn(),
    batchCreateParts: vi.fn(),
    uploadProjectImage: vi.fn(),
    updateProjectStatus: vi.fn(),
  },
}))

import { usePatternRoomPartActions } from '@/views/pattern-room/composables/usePatternRoomPartActions'
import { usePatternRoomProjectActions } from '@/views/pattern-room/composables/usePatternRoomProjectActions'
import type { ProjectCreateRequest, ProjectStatus, ProjectUpdateRequest } from '@/api/patternRoom'

/** 构造 403 错误（与 axios 错误形状一致：response.status） */
function httpError(status: number, message = '权限不足') {
  return Object.assign(new Error(message), { response: { status, data: { detail: message } } })
}

function makeRoleHook(overrides: Record<string, unknown> = {}) {
  return {
    roles: ref([]),
    currentRoleId: ref<number | null>(1),
    loading: ref(false),
    submitting: ref(false),
    error: ref<string | null>(null),
    errorStatus: ref<number | undefined>(undefined),
    getCurrentRole: () => ({ id: 1, role_name: '默认', current_version: 'T1', version: 1 }),
    setCurrentRole: vi.fn(),
    setRoleCurrentVersion: vi.fn(async () => ({ success: true })),
    createRole: vi.fn(async () => ({ success: true })),
    deleteRole: vi.fn(async () => ({ success: true })),
    ...overrides,
  }
}

function makeProjectHook(overrides: Record<string, unknown> = {}) {
  return {
    currentProject: ref({ id: 7, sequence_no: 'DY-001', version: 1 }),
    loading: ref(false),
    submitting: ref(false),
    error: ref<string | null>(null),
    errorStatus: ref<number | undefined>(undefined),
    fetchDetail: vi.fn(async () => null),
    create: vi.fn(async () => ({ id: 7, success: true })),
    update: vi.fn(async () => ({ success: true })),
    remove: vi.fn(async () => ({ success: true })),
    clearCurrent: vi.fn(),
    ...overrides,
  }
}

/** 驱动 usePatternRoomPartActions 的最小依赖集 */
function buildPartActions(roleHook = makeRoleHook()) {
  const partHook = {
    partsByVersion: ref([]),
    parts: ref([]),
    versionList: ref([]),
    finalVersion: ref('T1'),
    loading: ref(false),
    submitting: ref(false),
    error: ref<string | null>(null),
    setFinalVersion: vi.fn(),
    patchPart: vi.fn(),
    removePartLocal: vi.fn(),
    appendPart: vi.fn(),
    fetchPartsByVersion: vi.fn(async () => undefined),
    clearParts: vi.fn(),
  }
  const projectHook = makeProjectHook()
  const versionHook = { versions: ref([]), versionDetail: ref(null), fetchVersionDetail: vi.fn() }
  const actions = usePatternRoomPartActions({
    canManage: ref(true),
    confirmDialog: { confirm: vi.fn(async () => true) } as never,
    selectedProjectId: ref<number | null>(7),
    projectHook: projectHook as never,
    partHook: partHook as never,
    versionHook: versionHook as never,
    roleHook: roleHook as never,
  })
  return { actions, partHook }
}

/** 驱动 usePatternRoomProjectActions 的最小依赖集 */
function buildProjectActions(projectHook = makeProjectHook()) {
  const groupHook = {
    groups: ref([]),
    loading: ref(false),
    error: ref<string | null>(null),
    currentPage: ref(1),
    perPage: ref(20),
    loadGrouped: vi.fn(async () => undefined),
  }
  const actions = usePatternRoomProjectActions({
    canManage: ref(true),
    confirmDialog: { confirm: vi.fn(async () => true) } as never,
    groupHook: groupHook as never,
    projectHook: projectHook as never,
    selectedProjectId: ref<number | null>(7),
    searchKeyword: ref(''),
    statusFilter: ref<ProjectStatus>('in_progress'),
    isNarrow: ref(false),
    drawerOpen: ref(false),
    formPatternMakerId: ref<number | null>(null),
    onSelectProject: vi.fn(),
  })
  return { actions, groupHook }
}

describe('AUD-12 编排 Hook 的假成功缺口与 403 双弹', () => {
  beforeEach(() => {
    mocks.showToast.mockClear()
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
  })

  describe('roleHook.error 分支的 403 抑制', () => {
    it('设最终版本 403：不弹 toast（拦截器已提示）', async () => {
      const roleHook = makeRoleHook({
        error: ref('权限不足'),
        errorStatus: ref(403),
        setRoleCurrentVersion: vi.fn(async () => null),
      })
      const { actions } = buildPartActions(roleHook)

      await actions.onSetFinalVersion('T2')

      expect(mocks.showToast).not.toHaveBeenCalled()
    })

    it('设最终版本 500：弹 error toast（失败必须可见）', async () => {
      const roleHook = makeRoleHook({
        error: ref('设置最终版本失败'),
        errorStatus: ref(500),
        setRoleCurrentVersion: vi.fn(async () => null),
      })
      const { actions } = buildPartActions(roleHook)

      await actions.onSetFinalVersion('T2')

      expect(mocks.showToast).toHaveBeenCalledWith('设置最终版本失败', 'error')
    })

    it('复制版本后设最终版本 403：不弹 toast', async () => {
      const roleHook = makeRoleHook({
        error: ref('权限不足'),
        errorStatus: ref(403),
        setRoleCurrentVersion: vi.fn(async () => null),
      })
      const { patternRoomApi } = await import('@/api/patternRoom')
      vi.mocked(patternRoomApi.copyPartVersion).mockResolvedValue({
        success: true,
        message: 'ok',
        id: 99,
        version_no: 'T2',
      })
      const { actions, partHook } = buildPartActions(roleHook)

      await actions.onCopyPartVersion({ id: 42, part_name: '前片', version_no: 'T1', version: 1 } as never)

      expect(mocks.showToast).not.toHaveBeenCalled()
      // 403 也要刷新列表：复制接口已成功落库，不能停在旧数据上
      expect(partHook.fetchPartsByVersion).toHaveBeenCalled()
    })
  })

  describe('裸 await 写操作点的假成功缺口', () => {
    it('新增角色 500：弹 error toast', async () => {
      const roleHook = makeRoleHook({
        error: ref('新增角色失败'),
        errorStatus: ref(500),
        createRole: vi.fn(async () => null),
      })
      const { actions } = buildPartActions(roleHook)

      await actions.onAddRole('新角色')

      expect(mocks.showToast).toHaveBeenCalledWith('新增角色失败', 'error')
    })

    it('新增角色 403：不弹 toast', async () => {
      const roleHook = makeRoleHook({
        error: ref('权限不足'),
        errorStatus: ref(403),
        createRole: vi.fn(async () => null),
      })
      const { actions } = buildPartActions(roleHook)

      await actions.onAddRole('新角色')

      expect(mocks.showToast).not.toHaveBeenCalled()
    })

    it('删除角色 500：弹 error toast', async () => {
      const roleHook = makeRoleHook({
        error: ref('删除角色失败'),
        errorStatus: ref(500),
        deleteRole: vi.fn(async () => null),
      })
      const { actions } = buildPartActions(roleHook)

      await actions.onRemoveRole({ id: 1, role_name: '默认' })

      expect(mocks.showToast).toHaveBeenCalledWith('删除角色失败', 'error')
    })

    it('新增项目 500：弹 error toast 且弹窗不关闭', async () => {
      const projectHook = makeProjectHook({
        error: ref('新增打样项目失败'),
        errorStatus: ref(500),
        create: vi.fn(async () => null),
      })
      const { actions, groupHook } = buildProjectActions(projectHook)

      actions.openCreateProjectDialog()
      expect(actions.projectFormVisible.value).toBe(true)
      await actions.onProjectSubmitCreate({ product_name: '小熊' } as ProjectCreateRequest)

      expect(mocks.showToast).toHaveBeenCalledWith('新增打样项目失败', 'error')
      // 假成功缺口：失败时弹窗必须保持打开，且不得刷新列表/选中新项目
      expect(actions.projectFormVisible.value).toBe(true)
      expect(groupHook.loadGrouped).not.toHaveBeenCalled()
    })

    it('新增项目 403：不弹 toast', async () => {
      const projectHook = makeProjectHook({
        error: ref('权限不足'),
        errorStatus: ref(403),
        create: vi.fn(async () => null),
      })
      const { actions } = buildProjectActions(projectHook)

      await actions.onProjectSubmitCreate({ product_name: '小熊' } as ProjectCreateRequest)

      expect(mocks.showToast).not.toHaveBeenCalled()
    })

    it('编辑项目 500：弹 error toast 且弹窗不关闭', async () => {
      const projectHook = makeProjectHook({
        error: ref('编辑打样项目失败'),
        errorStatus: ref(500),
        update: vi.fn(async () => null),
      })
      const { actions, groupHook } = buildProjectActions(projectHook)

      actions.openEditProjectDialog()
      expect(actions.projectFormVisible.value).toBe(true)
      await actions.onProjectSubmitUpdate({ product_name: '小熊' } as ProjectUpdateRequest)

      expect(mocks.showToast).toHaveBeenCalledWith('编辑打样项目失败', 'error')
      expect(actions.projectFormVisible.value).toBe(true)
      expect(groupHook.loadGrouped).not.toHaveBeenCalled()
    })

    it('删除项目 500：弹 error toast 且保持选中态', async () => {
      const projectHook = makeProjectHook({
        error: ref('删除打样项目失败'),
        errorStatus: ref(500),
        remove: vi.fn(async () => null),
      })
      const { actions, groupHook } = buildProjectActions(projectHook)

      await actions.confirmDeleteProject()

      expect(mocks.showToast).toHaveBeenCalledWith('删除打样项目失败', 'error')
      // 失败不得清空当前项目与选中态
      expect(projectHook.clearCurrent).not.toHaveBeenCalled()
      expect(groupHook.loadGrouped).not.toHaveBeenCalled()
    })

    it('卡片点编辑但详情加载失败 500：弹 error toast 且不打开弹窗', async () => {
      const projectHook = makeProjectHook({
        error: ref('加载打样详情失败'),
        errorStatus: ref(500),
        fetchDetail: vi.fn(async () => null),
      })
      const { actions } = buildProjectActions(projectHook)

      await actions.onEditProjectFromCard(7)

      expect(mocks.showToast).toHaveBeenCalledWith('加载打样详情失败', 'error')
      // 失败不得打开编辑弹窗（否则表单基于空详情，保存即覆盖）
      expect(actions.projectFormVisible.value).toBe(false)
    })

    it('卡片点编辑详情加载失败 403：不弹 toast', async () => {
      const projectHook = makeProjectHook({
        error: ref('权限不足'),
        errorStatus: ref(403),
        fetchDetail: vi.fn(async () => null),
      })
      const { actions } = buildProjectActions(projectHook)

      await actions.onEditProjectFromCard(7)

      expect(mocks.showToast).not.toHaveBeenCalled()
    })
  })

  describe('后台上传失败', () => {
    it('上传 500：保留固定文案（不透出底层错误）', async () => {
      const { patternRoomApi } = await import('@/api/patternRoom')
      vi.mocked(patternRoomApi.uploadProjectImage).mockRejectedValue(httpError(500, 'Internal Server Error'))
      const { actions } = buildProjectActions()

      actions.onProjectUploadImage(new File([new Uint8Array([1])], 'a.png', { type: 'image/png' }))
      await actions.onProjectSubmitUpdate({ product_name: '小熊' } as ProjectUpdateRequest)

      await vi.waitFor(() => {
        expect(mocks.showToast).toHaveBeenCalledWith('图片上传失败，请重试', 'error')
      })
    })

    it('上传 403：不弹 toast（拦截器已提示）', async () => {
      const { patternRoomApi } = await import('@/api/patternRoom')
      vi.mocked(patternRoomApi.uploadProjectImage).mockRejectedValue(httpError(403))
      const { actions } = buildProjectActions()

      actions.onProjectUploadImage(new File([new Uint8Array([1])], 'a.png', { type: 'image/png' }))
      await actions.onProjectSubmitUpdate({ product_name: '小熊' } as ProjectUpdateRequest)

      // 让后台上传的 catch 有机会执行
      await vi.waitFor(() => {
        expect(patternRoomApi.uploadProjectImage).toHaveBeenCalled()
      })
      await new Promise((r) => setTimeout(r, 0))
      expect(mocks.showToast).not.toHaveBeenCalled()
    })
  })
})

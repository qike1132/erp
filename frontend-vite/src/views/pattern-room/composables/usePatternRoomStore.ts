/**
 * usePatternRoomStore — 打样模块统一状态管理
 *
 * 合并原 useSamplingProject + useSamplingPart 两个独立的 Hook，
 * 使用 currentProject 作为单一数据源，消除 parts 双存储和双重 HTTP 请求。
 *
 * 设计原则：
 *  - 单一数据源：currentProject 是唯一事实来源，parts 从它派生
 *  - 原子操作：selectProject(id) 一次请求加载全部数据，不再 split
 *  - 自动刷新：部位操作成功后自动调用 selectProject，调用方无需手动编排
 *  - 纯数据层：不包含 UI 副作用（toast 由调用方自行处理）
 *
 * @see useSamplingHelpers.ts — 共享错误处理工具
 */
import { ref, computed } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type {
  ProjectDetailResponse,
  ProjectCreateRequest,
  PartDetail,
  PartCreateRequest,
  PartUpdateRequest,
  ActionResponse,
} from '@/api/patternRoom'
import { withErrorHandling } from './useSamplingHelpers'

export function usePatternRoomStore() {
  // ==================================================================
  // 状态（单一数据源）
  // ==================================================================

  /** 当前选中项目的完整详情（含 parts） */
  const currentProject = ref<ProjectDetailResponse | null>(null)

  /** 项目详情加载中 */
  const loading = ref(false)

  /** 操作提交中（create/update/delete/upload） */
  const submitting = ref(false)

  /** 最近一次错误消息 */
  const error = ref<string | null>(null)

  // ==================================================================
  // 派生状态
  // ==================================================================

  /** 当前选中项目 ID（派生，不需要独立维护） */
  const selectedProjectId = computed<number | null>(() => currentProject.value?.id ?? null)

  /** 当前项目的部位列表（派生，不需要独立存储） */
  const parts = computed<PartDetail[]>(() => currentProject.value?.parts ?? [])

  // ==================================================================
  // 项目操作
  // ==================================================================

  /**
   * 选中并加载项目详情（原子操作，一次请求获取项目+部位）。
   * 替代原 onSelectProject → fetchDetail + watch → fetchParts 的隐式依赖链。
   */
  async function selectProject(id: number): Promise<ProjectDetailResponse | null> {
    loading.value = true
    error.value = null

    const result = await withErrorHandling(
      () => patternRoomApi.getProject(id),
      {
        setLoading: (v) => { loading.value = v },
        setError: (v) => { error.value = v },
        logPrefix: '[usePatternRoomStore]',
        fallbackMessage: '加载打样详情失败',
        resourceLabel: '打样项目',
      },
    )

    if (result) {
      currentProject.value = result
    } else {
      currentProject.value = null
    }
    return result
  }

  /**
   * 刷新当前项目（操作后调用）。
   * 如果未选中项目则不执行。
   */
  async function refreshProject(): Promise<ProjectDetailResponse | null> {
    const id = selectedProjectId.value
    if (id == null) return null
    return selectProject(id)
  }

  /**
   * 新增打样项目（自动生成序列号 + T1 基线版本）
   */
  async function createProject(data: ProjectCreateRequest): Promise<ActionResponse | null> {
    submitting.value = true
    const result = await withErrorHandling(
      () => patternRoomApi.createProject(data),
      {
        setLoading: (v) => { submitting.value = v },
        setError: (v) => { error.value = v },
        logPrefix: '[usePatternRoomStore]',
        fallbackMessage: '新增打样项目失败',
        resourceLabel: '打样项目',
      },
    )
    return result
  }

  /**
   * 上传产品图片（JPEG/PNG/WebP ≤ 10MB）
   */
  async function uploadImage(id: number, file: File): Promise<ActionResponse | null> {
    submitting.value = true
    const result = await withErrorHandling(
      () => patternRoomApi.uploadProjectImage(id, file),
      {
        setLoading: (v) => { submitting.value = v },
        setError: (v) => { error.value = v },
        logPrefix: '[usePatternRoomStore]',
        fallbackMessage: '图片上传失败',
        resourceLabel: '图片',
      },
    )
    return result
  }

  // ==================================================================
  // 部位操作（每个操作成功后自动 refreshProject）
  // ==================================================================

  /**
   * 新增部位。
   * 成功后自动刷新当前项目（一次 HTTP 请求替代原双重请求）。
   */
  async function createPart(data: PartCreateRequest): Promise<ActionResponse | null> {
    const projectId = selectedProjectId.value
    if (projectId == null) return null

    submitting.value = true
    const result = await withErrorHandling(
      () => patternRoomApi.createPart(projectId, data),
      {
        setLoading: (v) => { submitting.value = v },
        setError: (v) => { error.value = v },
        logPrefix: '[usePatternRoomStore]',
        fallbackMessage: '新增部位失败',
        resourceLabel: '部位',
      },
    )

    if (result) {
      await refreshProject()
    }
    return result
  }

  /**
   * 编辑部位布料（乐观锁校验，409 自动刷新）。
   * 成功后自动刷新当前项目。
   */
  async function updatePart(partId: number, data: PartUpdateRequest): Promise<ActionResponse | null> {
    if (selectedProjectId.value == null) return null

    submitting.value = true
    const result = await withErrorHandling(
      () => patternRoomApi.updatePart(partId, data),
      {
        setLoading: (v) => { submitting.value = v },
        setError: (v) => { error.value = v },
        logPrefix: '[usePatternRoomStore]',
        fallbackMessage: '编辑部位失败',
        resourceLabel: '部位',
        onConflict: async () => {
          await refreshProject()
        },
      },
    )

    if (result) {
      await refreshProject()
    }
    return result
  }

  /**
   * 删除部位。
   * 成功后自动刷新当前项目。
   */
  async function deletePart(partId: number): Promise<ActionResponse | null> {
    if (selectedProjectId.value == null) return null

    submitting.value = true
    const result = await withErrorHandling(
      () => patternRoomApi.deletePart(partId),
      {
        setLoading: (v) => { submitting.value = v },
        setError: (v) => { error.value = v },
        logPrefix: '[usePatternRoomStore]',
        fallbackMessage: '删除部位失败',
        resourceLabel: '部位',
      },
    )

    if (result) {
      await refreshProject()
    }
    return result
  }

  /**
   * 保留指定版本，删除同部位名称下的其他所有版本。
   * 成功后自动刷新当前项目。
   */
  async function keepVersion(partId: number): Promise<ActionResponse | null> {
    const projectId = selectedProjectId.value
    if (projectId == null) return null

    submitting.value = true
    const result = await withErrorHandling(
      () => patternRoomApi.keepVersion(projectId, partId),
      {
        setLoading: (v) => { submitting.value = v },
        setError: (v) => { error.value = v },
        logPrefix: '[usePatternRoomStore]',
        fallbackMessage: '保留版本失败',
        resourceLabel: '版本保留',
      },
    )

    if (result) {
      await refreshProject()
    }
    return result
  }

  // ==================================================================
  // 清理
  // ==================================================================

  /** 清空当前项目（重置所有状态） */
  function clearCurrent() {
    currentProject.value = null
    error.value = null
  }

  // ==================================================================
  // 导出
  // ==================================================================

  return {
    // 状态
    currentProject,
    loading,
    submitting,
    error,
    // 派生
    selectedProjectId,
    parts,
    // 项目操作
    selectProject,
    refreshProject,
    createProject,
    uploadImage,
    // 部位操作
    createPart,
    updatePart,
    deletePart,
    keepVersion,
    // 清理
    clearCurrent,
  }
}

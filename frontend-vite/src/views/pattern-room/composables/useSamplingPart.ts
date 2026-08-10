/**
 * useSamplingPart — 部位布料管理 Hook
 *
 * 封装部位列表查询、新增、编辑、删除的状态管理与 API 调用。
 * 接收响应式 projectId，watch 自动重新加载部位列表。
 * 对应 design.md 2.4.6 E3。
 */
import { ref, watch, type Ref } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type {
  PartDetail,
  PartCreateRequest,
  PartUpdateRequest,
  ActionResponse,
} from '@/api/patternRoom'
import { toast } from '@/composables/useToast'
import { getErrorMessage, getErrorStatus } from '@/types/errors'

/**
 * 根据 HTTP 状态码解析部位操作的错误消息
 * - 409 乐观锁冲突：数据已被他人更新，需刷新重试
 * - 404 资源不存在：可能已被删除
 * - 400 业务错误：使用后端返回的 detail
 */
function resolvePartErrorMessage(err: unknown, fallback: string): string {
  const status = getErrorStatus(err)
  if (status === 409) return '数据已被他人更新，请刷新后重试'
  if (status === 404) return '数据不存在，可能已被删除'
  if (status === 400) return getErrorMessage(err, '操作失败，请检查输入')
  return getErrorMessage(err, fallback)
}

export function useSamplingPart(projectId: Ref<number | null>) {
  /** 当前项目的部位列表（当前版本） */
  const parts = ref<PartDetail[]>([])
  /** 跨版本部位汇总（所有版本扁平列表，带 version_no） */
  const partsByVersion = ref<PartDetail[]>([])
  /** 版本号列表 */
  const versionList = ref<string[]>([])
  /** 加载中 */
  const loading = ref(false)
  /** 提交中（新增/编辑/删除） */
  const submitting = ref(false)
  /** 错误信息 */
  const error = ref<string | null>(null)

  /**
   * 加载部位列表
   */
  async function fetchParts(id: number): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await patternRoomApi.listParts(id)
      parts.value = res.items ?? []
    } catch (e) {
      console.error('[useSamplingPart] 查询部位列表失败:', e)
      const message = resolvePartErrorMessage(e, '加载部位列表失败')
      error.value = message
      toast.error(message)
      parts.value = []
    } finally {
      loading.value = false
    }
  }

  /**
   * 加载跨版本部位汇总（部位+版本二维表数据源）
   */
  async function fetchPartsByVersion(id: number): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const res = await patternRoomApi.getPartsByVersion(id)
      partsByVersion.value = res.items ?? []
      versionList.value = res.versions ?? []
    } catch (e) {
      console.error('[useSamplingPart] 查询跨版本部位数据失败:', e)
      partsByVersion.value = []
      versionList.value = []
    } finally {
      loading.value = false
    }
  }

  /**
   * 新增部位
   */
  async function create(data: PartCreateRequest): Promise<ActionResponse | null> {
    if (projectId.value == null) return null
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.createPart(projectId.value, data)
      // 刷新部位列表
      await fetchParts(projectId.value)
      return res
    } catch (e) {
      console.error('[useSamplingPart] 新增部位失败:', e)
      const message = resolvePartErrorMessage(e, '新增部位失败')
      error.value = message
      toast.error(message)
      return null
    } finally {
      submitting.value = false
    }
  }

  /**
   * 编辑部位（乐观锁校验）
   * - 409 冲突时自动刷新列表，便于用户看到最新数据后重试
   */
  async function update(partId: number, data: PartUpdateRequest): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.updatePart(partId, data)
      // 刷新部位列表
      if (projectId.value != null) {
        await fetchParts(projectId.value)
      }
      return res
    } catch (e) {
      console.error('[useSamplingPart] 编辑部位失败:', e)
      const message = resolvePartErrorMessage(e, '编辑部位失败')
      error.value = message
      toast.error(message)
      // 乐观锁冲突：自动刷新列表，让用户基于最新数据重试
      if (getErrorStatus(e) === 409 && projectId.value != null) {
        await fetchParts(projectId.value)
      }
      return null
    } finally {
      submitting.value = false
    }
  }

  /**
   * 删除部位
   */
  async function remove(partId: number): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.deletePart(partId)
      // 刷新部位列表
      if (projectId.value != null) {
        await fetchParts(projectId.value)
      }
      return res
    } catch (e) {
      console.error('[useSamplingPart] 删除部位失败:', e)
      const message = resolvePartErrorMessage(e, '删除部位失败')
      error.value = message
      toast.error(message)
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 清空部位状态 */
  function clearParts() {
    parts.value = []
    partsByVersion.value = []
    versionList.value = []
    error.value = null
  }

  // watch projectId 自动重新加载部位列表 + 跨版本汇总
  watch(
    projectId,
    (newId) => {
      if (newId != null) {
        fetchParts(newId)
        fetchPartsByVersion(newId)
      } else {
        clearParts()
      }
    },
    { immediate: true },
  )

  return {
    parts,
    partsByVersion,
    versionList,
    loading,
    submitting,
    error,
    fetchParts,
    fetchPartsByVersion,
    create,
    update,
    remove,
    clearParts,
  }
}

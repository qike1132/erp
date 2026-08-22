/**
 * useSamplingVersion — 版本管理 Hook
 *
 * 封装版本列表查询、版本详情查询、创建新版本的状态管理与 API 调用。
 * 接收响应式 projectId，watch 自动重新加载版本列表。
 * 对应 design.md 2.4.6 E4。
 */
import { ref, computed, watch, type Ref } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type {
  VersionBrief,
  VersionDetailResponse,
  ActionResponse,
} from '@/api/patternRoom'
import { toast } from '@/composables/useToast'
import { getErrorMessage, getErrorStatus } from '@/types/errors'

/**
 * 根据 HTTP 状态码解析版本操作的错误消息
 * - 409 乐观锁冲突：数据已被他人更新，需刷新重试
 * - 404 资源不存在：可能已被删除
 * - 400 业务错误：使用后端返回的 detail
 */
function resolveVersionErrorMessage(err: unknown, fallback: string): string {
  const status = getErrorStatus(err)
  if (status === 409) return '数据已被他人更新，请刷新后重试'
  if (status === 404) return '数据不存在，可能已被删除'
  if (status === 400) return getErrorMessage(err, '操作失败，请检查输入')
  return getErrorMessage(err, fallback)
}

export function useSamplingVersion(
  projectId: Ref<number | null>,
  currentRoleId: Ref<number | null> = ref(null),
) {
  /** 版本列表（按 version_no 升序） */
  const versions = ref<VersionBrief[]>([])
  /** 当前选中版本 ID */
  const currentVersionId = ref<number | null>(null)
  /** 当前版本详情 */
  const versionDetail = ref<VersionDetailResponse | null>(null)
  /** 加载中 */
  const loading = ref(false)
  /** 提交中（创建新版本） */
  const submitting = ref(false)
  /** 错误信息 */
  const error = ref<string | null>(null)

  /** 竞态保护：快速切换项目时忽略旧响应 */
  let _requestId = 0

  /** 加载版本列表 */
  async function fetchVersions(id: number): Promise<void> {
    const reqId = ++_requestId
    loading.value = true
    error.value = null
    try {
      const res = await patternRoomApi.listVersions(id)
      if (reqId !== _requestId) return
      versions.value = res.items ?? []
      // 默认选中最新版本（列表按 version_no 升序，取最后一个）
      if (versions.value.length > 0 && currentVersionId.value == null) {
        const latest = versions.value[versions.value.length - 1]
        if (latest) currentVersionId.value = latest.id
      }
    } catch (e) {
      if (reqId !== _requestId) return
      console.error('[useSamplingVersion] 查询版本列表失败:', e)
      const message = resolveVersionErrorMessage(e, '加载版本列表失败')
      error.value = message
      toast.error(message)
      versions.value = []
    } finally {
      if (reqId === _requestId) loading.value = false
    }
  }

  /**
   * 查询版本详情
   * - T1（is_baseline=true）：返回 full_snapshot
   * - T2+ 正常：返回 change_summary（预计算 diff）
   * - 降级（degraded=true）：返回 full_snapshot + 警告
   */
  async function fetchVersionDetail(versionId: number): Promise<VersionDetailResponse | null> {
    const reqId = ++_requestId
    loading.value = true
    error.value = null
    try {
      const res = await patternRoomApi.getVersionDetail(versionId)
      if (reqId !== _requestId) return null
      versionDetail.value = res
      currentVersionId.value = versionId
      return res
    } catch (e) {
      if (reqId !== _requestId) return null
      console.error('[useSamplingVersion] 查询版本详情失败:', e)
      const message = resolveVersionErrorMessage(e, '加载版本详情失败')
      error.value = message
      toast.error(message)
      versionDetail.value = null
      return null
    } finally {
      if (reqId === _requestId) loading.value = false
    }
  }

  /**
   * 创建新版本（快照当前部位布料 + 计算相对前一版本 diff）
   * @param reason 变更原因（可选）
   * @returns 创建结果 { version_id, version_no } 或 null
   * - 409 冲突时自动刷新版本列表，便于用户看到最新数据后重试
   */
  async function createVersion(reason?: string): Promise<ActionResponse | null> {
    if (projectId.value == null) return null
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.createVersion(
        projectId.value,
        { reason },
        currentRoleId.value ?? undefined,
      )
      // 刷新版本列表
      await fetchVersions(projectId.value)
      // 自动切换到新版本
      if (res.version_id != null) {
        await fetchVersionDetail(res.version_id)
      }
      return res
    } catch (e) {
      console.error('[useSamplingVersion] 创建新版本失败:', e)
      const message = resolveVersionErrorMessage(e, '创建新版本失败')
      error.value = message
      toast.error(message)
      // 乐观锁冲突：自动刷新版本列表，让用户基于最新数据重试
      if (getErrorStatus(e) === 409 && projectId.value != null) {
        await fetchVersions(projectId.value)
      }
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 是否基线版本（T1） */
  const isBaseline = computed(() => versionDetail.value?.is_baseline ?? false)
  /** 是否降级展示（前一版本缺失） */
  const isDegraded = computed(() => versionDetail.value?.degraded ?? false)
  /** 当前版本号 */
  const currentVersionNo = computed(() => versionDetail.value?.version_no ?? '')

  /** 清空版本状态 */
  function clearVersions() {
    versions.value = []
    currentVersionId.value = null
    versionDetail.value = null
    error.value = null
  }

  // watch projectId 自动重新加载版本列表
  watch(
    projectId,
    (newId) => {
      if (newId != null) {
        currentVersionId.value = null
        fetchVersions(newId)
      } else {
        clearVersions()
      }
    },
    { immediate: true },
  )

  // watch currentVersionId 自动加载版本详情
  watch(currentVersionId, (newId, oldId) => {
    if (newId != null && newId !== oldId) {
      fetchVersionDetail(newId)
    }
  })

  return {
    versions,
    currentVersionId,
    versionDetail,
    loading,
    submitting,
    error,
    isBaseline,
    isDegraded,
    currentVersionNo,
    fetchVersions,
    fetchVersionDetail,
    createVersion,
    clearVersions,
  }
}

/**
 * useSamplingProject — 打样项目 CRUD Hook
 *
 * 封装打样项目详情查询、新增、编辑、删除、图片上传的状态管理与 API 调用。
 * 对应 design.md 2.4.6 E2。
 */
import { ref } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type {
  ProjectDetailResponse,
  ProjectCreateRequest,
  ProjectUpdateRequest,
  ActionResponse,
} from '@/api/patternRoom'
import { toast } from '@/composables/useToast'
import { getErrorMessage, getErrorStatus } from '@/types/errors'

/**
 * 根据 HTTP 状态码解析打样项目操作的错误消息
 * - 409 乐观锁冲突：数据已被他人更新，需刷新重试
 * - 404 资源不存在：可能已被删除
 * - 400 业务错误：使用后端返回的 detail
 */
function resolveProjectErrorMessage(err: unknown, fallback: string): string {
  const status = getErrorStatus(err)
  if (status === 409) return '数据已被他人更新，请刷新后重试'
  if (status === 404) return '数据不存在，可能已被删除'
  if (status === 400) return getErrorMessage(err, '操作失败，请检查输入')
  return getErrorMessage(err, fallback)
}

export function useSamplingProject() {
  /** 当前选中项目详情 */
  const currentProject = ref<ProjectDetailResponse | null>(null)
  /** 加载中 */
  const loading = ref(false)
  /** 提交中（新增/编辑/删除/上传） */
  const submitting = ref(false)
  /** 错误信息 */
  const error = ref<string | null>(null)

  /** 详情查询序号：并发 fetchDetail 时仅应用最新一次结果，避免旧响应覆盖新数据 */
  let detailFetchSeq = 0

  /**
   * 获取打样项目详情（含部位布料 + 版本列表）
   */
  async function fetchDetail(id: number): Promise<ProjectDetailResponse | null> {
    const seq = ++detailFetchSeq
    loading.value = true
    error.value = null
    try {
      const res = await patternRoomApi.getProject(id)
      if (seq === detailFetchSeq) {
        currentProject.value = res
      }
      return res
    } catch (e) {
      console.error('[useSamplingProject] 查询详情失败:', e)
      const message = resolveProjectErrorMessage(e, '加载打样详情失败')
      if (seq === detailFetchSeq) {
        error.value = message
        currentProject.value = null
      }
      toast.error(message)
      return null
    } finally {
      if (seq === detailFetchSeq) {
        loading.value = false
      }
    }
  }

  /**
   * 新增打样项目（自动生成序列号 + T1 基线版本）
   * @returns 创建结果 { id, sequence_no } 或 null
   */
  async function create(data: ProjectCreateRequest): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.createProject(data)
      return res
    } catch (e) {
      console.error('[useSamplingProject] 新增打样项目失败:', e)
      const message = resolveProjectErrorMessage(e, '新增打样项目失败')
      error.value = message
      toast.error(message)
      return null
    } finally {
      submitting.value = false
    }
  }

  /**
   * 编辑打样项目（乐观锁校验）
   * - 409 冲突时自动刷新详情，便于用户看到最新数据后重试
   */
  async function update(id: number, data: ProjectUpdateRequest): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.updateProject(id, data)
      return res
    } catch (e) {
      console.error('[useSamplingProject] 编辑打样项目失败:', e)
      const message = resolveProjectErrorMessage(e, '编辑打样项目失败')
      error.value = message
      toast.error(message)
      // 乐观锁冲突：自动刷新详情，让用户基于最新数据重试
      if (getErrorStatus(e) === 409) {
        await fetchDetail(id)
      }
      return null
    } finally {
      submitting.value = false
    }
  }

  /**
   * 删除打样项目（级联删除部位/版本/日志，先写审计日志）
   */
  async function remove(id: number): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.deleteProject(id)
      return res
    } catch (e) {
      console.error('[useSamplingProject] 删除打样项目失败:', e)
      const message = resolveProjectErrorMessage(e, '删除打样项目失败')
      error.value = message
      toast.error(message)
      return null
    } finally {
      submitting.value = false
    }
  }

  /**
   * 上传产品图片（multipart/form-data，限制 JPEG/PNG/WebP ≤ 10MB）
   * @returns 上传结果 { file_id, url } 或 null
   */
  async function uploadImage(id: number, file: File): Promise<ActionResponse | null> {
    submitting.value = true
    error.value = null
    try {
      const res = await patternRoomApi.uploadProjectImage(id, file)
      return res
    } catch (e) {
      console.error('[useSamplingProject] 上传产品图片失败:', e)
      const message = resolveProjectErrorMessage(e, '图片上传失败')
      error.value = message
      toast.error(message)
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 清空当前项目详情 */
  function clearCurrent() {
    currentProject.value = null
    error.value = null
  }

  return {
    currentProject,
    loading,
    submitting,
    error,
    fetchDetail,
    create,
    update,
    remove,
    uploadImage,
    clearCurrent,
  }
}

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
import { getErrorStatus } from '@/types/errors'
import { resolveSamplingErrorMessage } from './useSamplingErrors'

export function useSamplingProject() {
  /** 当前选中项目详情 */
  const currentProject = ref<ProjectDetailResponse | null>(null)
  /** 加载中 */
  const loading = ref(false)
  /** 提交中（新增/编辑/删除/上传） */
  const submitting = ref(false)
  /** 错误信息 */
  const error = ref<string | null>(null)
  /**
   * 最近一次失败的状态码。
   *
   * 本 hook 的写操作在内部 catch 后统一返回 null，调用方拿不到异常对象；
   * 而 403 已由 axios 拦截器统一提示，调用方若只凭 error 文案再弹一次 toast
   * 就会同一次失败弹两条。故把状态码一并暴露，让调用方复用同一套 403 抑制口径。
   */
  const errorStatus = ref<number | undefined>(undefined)

  /** 详情查询序号：并发 fetchDetail 时仅应用最新一次结果，避免旧响应覆盖新数据 */
  let detailFetchSeq = 0

  /**
   * 获取打样项目详情（含部位布料 + 版本列表）
   */
  async function fetchDetail(id: number): Promise<ProjectDetailResponse | null> {
    const seq = ++detailFetchSeq
    loading.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.getProject(id)
      if (seq === detailFetchSeq) {
        currentProject.value = res
      }
      return res
    } catch (e) {
      console.error('[useSamplingProject] 查询详情失败:', e)
      const message = resolveSamplingErrorMessage(e, '加载打样详情失败')
      if (seq === detailFetchSeq) {
        error.value = message
        // 调用方靠 errorStatus 抑制 403 的重复 toast；不写会沿用上一次操作的状态码
        errorStatus.value = getErrorStatus(e)
        currentProject.value = null
      }
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
    // AUD-10（2026-10-24 审计）：重入守卫——双击「创建」曾并发发出两个 createProject
    // 建出两个重复项目（按钮/hook/函数三层均无防护）。同 usePatternRoomPartActions:82 款。
    if (submitting.value) return null
    submitting.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.createProject(data)
      return res
    } catch (e) {
      console.error('[useSamplingProject] 新增打样项目失败:', e)
      const message = resolveSamplingErrorMessage(e, '新增打样项目失败')
      error.value = message
      errorStatus.value = getErrorStatus(e)
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
    if (submitting.value) return null  // AUD-10 重入守卫
    submitting.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.updateProject(id, data)
      return res
    } catch (e) {
      console.error('[useSamplingProject] 编辑打样项目失败:', e)
      const message = resolveSamplingErrorMessage(e, '编辑打样项目失败')
      const status = getErrorStatus(e)
      // 乐观锁冲突：自动刷新详情，让用户基于最新数据重试。
      // fetchDetail 入口会重置 error/errorStatus，故先取本地副本、刷新完再回写，
      // 否则冲突文案被冲掉、调用方只能拿到兜底文案
      if (status === 409) {
        await fetchDetail(id)
      }
      error.value = message
      errorStatus.value = status
      return null
    } finally {
      submitting.value = false
    }
  }

  /**
   * 删除打样项目（级联删除部位/版本/日志，先写审计日志）
   */
  async function remove(id: number): Promise<ActionResponse | null> {
    if (submitting.value) return null  // AUD-10 重入守卫
    submitting.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.deleteProject(id)
      return res
    } catch (e) {
      console.error('[useSamplingProject] 删除打样项目失败:', e)
      const message = resolveSamplingErrorMessage(e, '删除打样项目失败')
      error.value = message
      errorStatus.value = getErrorStatus(e)
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
      const message = resolveSamplingErrorMessage(e, '图片上传失败')
      error.value = message
      return null
    } finally {
      submitting.value = false
    }
  }

  /** 清空当前项目详情 */
  function clearCurrent() {
    currentProject.value = null
    error.value = null
    errorStatus.value = undefined
  }

  return {
    currentProject,
    loading,
    submitting,
    error,
    errorStatus,
    fetchDetail,
    create,
    update,
    remove,
    uploadImage,
    clearCurrent,
  }
}

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

/**
 * 详情查询结果。
 *
 * 并发查询时「先发后到」很常见（点 A 卡片编辑、随即点 B 卡片）。旧实现把
 * 任何一次响应都 `return res`，于是过期的那次也会被调用方当成「最新详情」拿去
 * 打开编辑弹窗 —— 表单字段来自 A、保存却打到当前选中的 B，用户看不到任何异常。
 * 所以把「被取代」显式建模成一种结果，调用方必须自己决定怎么处理（M9）。
 *
 * - `ok`    ：这次查询就是最新的一次，detail 可信
 * - `stale` ：已被更新的查询取代，结果不可用；不是失败，不该报错
 * - `error` ：请求失败（error/errorStatus 已写入 hook 状态）
 */
export type DetailFetchOutcome =
  | { status: 'ok'; detail: ProjectDetailResponse }
  | { status: 'stale' }
  | { status: 'error' }

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
   * 获取打样项目详情（含部位布料 + 版本列表）。
   *
   * 始终返回三态结果，绝不把过期响应当成有效详情交出去（M9）。
   */
  async function fetchDetail(id: number): Promise<DetailFetchOutcome> {
    const seq = ++detailFetchSeq
    loading.value = true
    error.value = null
    errorStatus.value = undefined
    try {
      const res = await patternRoomApi.getProject(id)
      // 已被更新的查询取代：结果丢弃，且不能返回给调用方（否则表单填的是别人的数据）
      if (seq !== detailFetchSeq) return { status: 'stale' }
      currentProject.value = res
      return { status: 'ok', detail: res }
    } catch (e) {
      console.error('[useSamplingProject] 查询详情失败:', e)
      const message = resolveSamplingErrorMessage(e, '加载打样详情失败')
      // 过期的失败同样不该覆盖最新一次的状态（否则新查询成功也会显示旧错误）
      if (seq !== detailFetchSeq) return { status: 'stale' }
      error.value = message
      // 调用方靠 errorStatus 抑制 403 的重复 toast；不写会沿用上一次操作的状态码
      errorStatus.value = getErrorStatus(e)
      currentProject.value = null
      return { status: 'error' }
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

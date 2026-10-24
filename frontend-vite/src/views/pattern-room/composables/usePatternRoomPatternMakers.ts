/**
 * usePatternRoomPatternMakers — 版师列表管理 Hook
 *
 * 封装项目表单弹窗所需的版师选项：列表加载、新增、删除。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { ref, type Ref } from 'vue'
import type { useConfirmDialog } from '@/composables/useConfirmDialog'
import { patternMakerApi } from '@/api/patternMaker'
import type { PatternMaker } from '@/api/patternMaker'
import { showToast } from '@/composables/useToast'
import { getErrorStatus } from '@/types/errors'
import { resolveSamplingErrorMessage } from './useSamplingErrors'
import { usePatternRoomStore, resolveSwr } from '@/stores/patternRoom'
import { createManageGuard } from './useManageGuard'

type ConfirmDialog = ReturnType<typeof useConfirmDialog>

export function usePatternRoomPatternMakers(
  canManage: Ref<boolean>,
  confirmDialog: ConfirmDialog,
) {
  /** 版师列表（项目表单选项） */
  const patternMakers = ref<PatternMaker[]>([])
  /** 弹窗当前选中的版师 ID（v-model 双向绑定） */
  const formPatternMakerId = ref<number | null>(null)

  const store = usePatternRoomStore()
  /** 统一写权限守卫（替代 2 处重复的 canManage 检查） */
  const requireManage = createManageGuard(canManage)
  /** 前台加载序号：后台静默刷新结果仅在无新加载时应用 */
  let seq = 0

  /**
   * 加载版师列表（SWR 缓存）
   * @param force 跳过缓存强制请求（新增/删除版师后传 true）
   */
  async function loadPatternMakers(force = false): Promise<void> {
    // 无管理权限不请求版师列表：接口要求 customer_sampling_manage，避免导航竞态下触发 403
    if (!canManage.value) return
    // SWR 策略由 store 的 resolveSwr 统一实现（KD-1），与 useCustomerSampling 共用同一分支
    if (!force) {
      const seqAtStart = seq
      const outcome = await resolveSwr({
        getSnapshot: () => store.getMakersSnapshot(),
        fetch: () => store.fetchMakers(),
        apply: (data) => { patternMakers.value = data },
        // 前台加载会递增 seq，据此丢弃已过期的后台刷新结果
        isCurrent: () => seq === seqAtStart,
        logLabel: '[PatternRoomView] 后台刷新版师列表失败',
      })
      if (outcome !== 'miss') return
    }

    seq += 1
    try {
      const data = await store.fetchMakers()
      if (data) patternMakers.value = data
    } catch (e) {
      console.error('[PatternRoomView] 加载版师列表失败:', e)
      // F1b-06（2026-10-24 审计）：静默吞错会让有管理权限的用户误判「还没建过
      // 版师」而重复新建——失败必须可感知（全局拦截器对非 401/403 无兜底）。
      showToast('版师列表加载失败，请刷新重试', 'error')
    }
  }

  /** 新增版师：调用接口、刷新列表并选中新增项 */
  async function handleAddPatternMaker(name: string) {
    if (!requireManage()) return
    try {
      const res = await patternMakerApi.create({ name })
      if (res.success) {
        store.invalidateMakers()
        await loadPatternMakers(true)
        if (res.id != null) {
          formPatternMakerId.value = res.id
        }
      }
    } catch (e) {
      console.error('[PatternRoomView] 新增版师失败:', e)
      if (getErrorStatus(e) !== 403) {
        showToast(resolveSamplingErrorMessage(e, '新增版师失败'), 'error')
      }
    }
  }

  /** 删除版师：调用接口、刷新列表，若删除的是当前选中项则清空选择 */
  async function handleDeletePatternMaker(id: number) {
    if (!requireManage()) return
    const ok = await confirmDialog.confirm(
      '确认删除该版师？',
      '关联的打样项目将变为「未分类」，不会删除项目数据。',
      'danger',
    )
    if (!ok) return
    try {
      const res = await patternMakerApi.delete(id)
      if (res.success) {
        if (formPatternMakerId.value === id) {
          formPatternMakerId.value = null
        }
        store.invalidateMakers()
        await loadPatternMakers(true)
      }
    } catch (e) {
      console.error('[PatternRoomView] 删除版师失败:', e)
      // 403 已由 axios 拦截器统一提示，避免双 toast
      if (getErrorStatus(e) !== 403) {
        showToast(resolveSamplingErrorMessage(e, '删除版师失败'), 'error')
      }
    }
  }

  return {
    patternMakers,
    formPatternMakerId,
    loadPatternMakers,
    handleAddPatternMaker,
    handleDeletePatternMaker,
  }
}

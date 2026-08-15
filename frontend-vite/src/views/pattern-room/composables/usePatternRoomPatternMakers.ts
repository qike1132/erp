/**
 * usePatternRoomPatternMakers — 版师列表管理 Hook
 *
 * 封装项目表单弹窗所需的版师选项：列表加载、新增、删除。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { ref, type Ref } from 'vue'
import { toast } from '@/composables/useToast'
import type { useConfirmDialog } from '@/composables/useConfirmDialog'
import { patternMakerApi } from '@/api/patternMaker'
import type { PatternMaker } from '@/api/patternMaker'

type ConfirmDialog = ReturnType<typeof useConfirmDialog>

export function usePatternRoomPatternMakers(
  canManage: Ref<boolean>,
  confirmDialog: ConfirmDialog,
) {
  /** 版师列表（项目表单选项） */
  const patternMakers = ref<PatternMaker[]>([])
  /** 弹窗当前选中的版师 ID（v-model 双向绑定） */
  const formPatternMakerId = ref<number | null>(null)

  async function loadPatternMakers() {
    try {
      const res = await patternMakerApi.list()
      patternMakers.value = res.items ?? []
    } catch (e) {
      console.error('[PatternRoomView] 加载版师列表失败:', e)
    }
  }

  /** 新增版师：调用接口、刷新列表并选中新增项 */
  async function handleAddPatternMaker(name: string) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
    try {
      const res = await patternMakerApi.create({ name })
      if (res.success) {
        await loadPatternMakers()
        if (res.id != null) {
          formPatternMakerId.value = res.id
        }
        toast.success('版师添加成功')
      } else {
        toast.error(res.message || '版师添加失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 新增版师失败:', e)
      toast.error('版师添加失败')
    }
  }

  /** 删除版师：调用接口、刷新列表，若删除的是当前选中项则清空选择 */
  async function handleDeletePatternMaker(id: number) {
    if (!canManage.value) {
      toast.warning('无操作权限')
      return
    }
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
        await loadPatternMakers()
        toast.success('版师删除成功')
      } else {
        toast.error(res.message || '版师删除失败')
      }
    } catch (e) {
      console.error('[PatternRoomView] 删除版师失败:', e)
      toast.error('版师删除失败')
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

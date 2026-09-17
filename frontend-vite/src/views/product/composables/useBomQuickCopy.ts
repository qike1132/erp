import { ref, reactive, onUnmounted, type Ref } from 'vue'
import { productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { resolveCopyTargetRole } from './bomTypes'
import type { BomSearchProduct, ProgressState, Role } from './bomTypes'

interface UseBomQuickCopyDeps {
  currentProductId: Ref<number | null>
  reloadBom: (productId: number) => Promise<void>
  /** 当前选中的角色；null = 默认 BOM 作用域，复制物料将归属到该角色 */
  selectedRole: Ref<Role | null>
  /** 复制成功后按 id 回选目标角色（新建角色落库后 id 会变） */
  selectRoleById: (roleId: number) => void
}

/**
 * BOM 快速复制（UiAutocomplete 驱动）
 * 简化版：自动补全委托给 UiAutocomplete，本模块只处理复制逻辑。
 */
export function useBomQuickCopy({ currentProductId, reloadBom, selectedRole, selectRoleById }: UseBomQuickCopyDeps) {
  const quickCopyKeyword = ref('')
  const quickCopyLoading = ref(false)
  const quickCopyProgress = reactive<ProgressState>({ visible: false, percent: 0, text: '' })

  let selectedSourceProductId: number | null = null
  let selectedSourceProductName: string | null = null

  // 复制成功后隐藏进度条的定时器，卸载时需清理
  let _copyTimer: ReturnType<typeof setTimeout> | null = null
  onUnmounted(() => {
    if (_copyTimer) clearTimeout(_copyTimer)
  })

  // ============================================================
  // UiAutocomplete 搜索函数
  // ============================================================
  async function searchProductsForBom(keyword: string): Promise<BomSearchProduct[]> {
    if (!keyword.trim()) return []
    try {
      const res = (await productApi.searchProductsForBom(keyword)) as unknown as { success: boolean; products?: BomSearchProduct[] }
      return res.success && res.products && res.products.length > 0 ? res.products : []
    } catch {
      return []
    }
  }

  // ============================================================
  // 选中处理
  // ============================================================
  function selectAutocompleteItem(item: BomSearchProduct) {
    selectedSourceProductId = item.id
    selectedSourceProductName = item.name
  }

  // ============================================================
  // 执行复制
  // ============================================================
  async function quickCopyBom() {
    const keyword = quickCopyKeyword.value.trim()

    // 优先使用已选中的产品
    if (selectedSourceProductId && selectedSourceProductName) {
      return executeCopy(selectedSourceProductId, selectedSourceProductName)
    }

    // 回退：通过关键词搜索
    if (!keyword) {
      showToast('请先搜索并选择产品，或输入产品名称', 'warning')
      return
    }

    quickCopyLoading.value = true
    showProgress(10, '搜索产品中...')

    try {
      const res = (await productApi.searchProductsForBom(keyword)) as unknown as { success: boolean; products?: BomSearchProduct[] }
      if (!res.success || !res.products?.length) {
        hideProgress()
        quickCopyLoading.value = false
        showToast('未找到匹配的产品', 'warning')
        return
      }
      const withBom = res.products.filter((p: BomSearchProduct) => p.has_bom)
      if (!withBom.length) {
        hideProgress()
        quickCopyLoading.value = false
        showToast('找到的产品没有配置BOM表', 'warning')
        return
      }
      const first = withBom[0]
      if (first) return executeCopy(first.id, first.name)
    } catch {
      hideProgress()
      quickCopyLoading.value = false
      showToast('搜索失败', 'error')
    }
  }

  async function executeCopy(sourceId: number, sourceName: string) {
    // 解析复制归属角色：未保存的新角色按名称交给后端查找或新建，无需先保存
    const target = resolveCopyTargetRole(selectedRole.value)
    if (!target.ok) {
      hideProgress()
      quickCopyLoading.value = false
      showToast(target.message, 'warning')
      return
    }

    showProgress(40, `正在从 "${sourceName}" 复制BOM...`)

    try {
      showProgress(70, '执行复制...')
      // 角色模式下 overwrite 仅作用于目标角色（后端已按 role_id 收敛删除范围）
      const res = (await productApi.copyBom(
        currentProductId.value!, sourceId, true, target.roleId, target.roleName ?? null,
      )) as { success: boolean; error?: string; target_role?: { id: number; name: string } }
      if (res.success) {
        showProgress(100, '复制成功！')
        _copyTimer = setTimeout(async () => {
          hideProgress()
          quickCopyLoading.value = false
          if (currentProductId.value) await reloadBom(currentProductId.value)
          // reload 会把选中项停靠回「默认BOM」（A-3），若本次复制到具体角色需回选该角色
          if (res.target_role?.id != null) selectRoleById(res.target_role.id)
          quickCopyKeyword.value = ''
          selectedSourceProductId = null
          selectedSourceProductName = null
        }, 500)
      } else {
        hideProgress()
        quickCopyLoading.value = false
        showToast(res.error || '复制失败', 'error')
      }
    } catch {
      hideProgress()
      quickCopyLoading.value = false
      showToast('复制失败', 'error')
    }
  }

  function showProgress(percent: number, text: string) {
    quickCopyProgress.visible = true
    quickCopyProgress.percent = percent
    quickCopyProgress.text = text
  }
  function hideProgress() {
    quickCopyProgress.visible = false
  }

  return {
    quickCopyKeyword,
    quickCopyLoading,
    quickCopyProgress,
    searchProductsForBom,
    selectAutocompleteItem,
    quickCopyBom,
  }
}

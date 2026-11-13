import { ref, reactive, onUnmounted, type Ref } from 'vue'
import { productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { BomSearchProduct, ProgressState } from './bomTypes'

interface UseBomQuickCopyDeps {
  currentProductId: Ref<number | null>
  /** 当前产品名（用于覆盖确认文案） */
  currentProductName: Ref<string>
  reloadBom: (productId: number) => Promise<void>
  /**
   * 「另一种破坏性操作是否在途」判定（宿主注入 `bomSaving`）。
   * 复制与保存都是全量替换语义，复制成功后 reloadBom 会整份重载编辑基线，
   * 与在途保存互相覆盖；在途时一律拒绝发起复制。
   */
  isBusy: () => boolean
  /** 覆盖前的二次确认（目标产品已有 BOM 物料或角色时调用） */
  confirmOverwrite: (productName: string) => Promise<boolean>
}

/**
 * BOM 快速复制（UiAutocomplete 驱动）
 * 简化版：自动补全委托给 UiAutocomplete，本模块只处理复制逻辑。
 */
export function useBomQuickCopy({
  currentProductId, currentProductName, reloadBom, isBusy, confirmOverwrite,
}: UseBomQuickCopyDeps) {
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
    // 2026-10-18 OCR 评审：保存进行中拒绝复制。两者都是全量替换语义，
    // 且复制成功后 reloadBom 会整份重载编辑基线，与在途保存互相覆盖。
    if (isBusy()) {
      showToast('保存进行中，请稍候再复制', 'warning')
      return
    }

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
    quickCopyLoading.value = true

    // 2026-11-13（owner 定）：快速复制一律「整份复制」——把源 SKU 的默认 BOM
    // 与其全部角色结构一并复制到目标产品，忽略当前选中的角色页签。
    // 目标已有物料或角色定义时，后端 overwrite=true 会先删目标四张 BOM 表
    // （含 ProductRole，DB 级 CASCADE 连其物料），故必须先二次确认。
    if (currentProductId.value != null) {
      try {
        const existing = (await productApi.loadBom(currentProductId.value)) as {
          success?: boolean
          materials?: unknown[]
          product?: { roles?: unknown[] }
        }
        if (!existing?.success) {
          hideProgress()
          quickCopyLoading.value = false
          showToast('读取目标产品 BOM 失败，已取消复制', 'error')
          return
        }
        // 角色定义也算「已有 BOM」：整份复制会把目标角色一起删掉重建
        if ((existing.materials?.length ?? 0) > 0 || (existing.product?.roles?.length ?? 0) > 0) {
          const ok = await confirmOverwrite(currentProductName.value)
          if (!ok) {
            hideProgress()
            quickCopyLoading.value = false
            return
          }
        }
      } catch {
        // 读取失败时无法确认是否覆盖，宁可中止并提示
        hideProgress()
        quickCopyLoading.value = false
        showToast('读取目标产品 BOM 失败，已取消复制', 'error')
        return
      }
    }

    showProgress(40, `正在从 "${sourceName}" 复制BOM...`)

    try {
      showProgress(70, '执行复制...')
      // 不传 role_id / role_name：整份复制（默认 BOM + 源产品全部角色及其物料）
      const res = (await productApi.copyBom(
        currentProductId.value!, sourceId, true,
      )) as { success: boolean; error?: string }
      if (res.success) {
        showProgress(100, '复制成功！')
        _copyTimer = setTimeout(async () => {
          hideProgress()
          quickCopyLoading.value = false
          if (currentProductId.value) await reloadBom(currentProductId.value)
          quickCopyKeyword.value = ''
          selectedSourceProductId = null
          selectedSourceProductName = null
        }, 500)
      } else {
        hideProgress()
        quickCopyLoading.value = false
        showToast(res.error || '复制失败', 'error')
      }
    } catch (err) {
      hideProgress()
      quickCopyLoading.value = false
      // 后端业务校验是 400 + detail（如源产品无 BOM），必须透出真实原因，
      // 否则只剩「复制失败」，用户无法判断为什么没复制过来。
      showToast(getErrorMessage(err, '复制失败'), 'error')
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

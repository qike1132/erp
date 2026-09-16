import { ref, reactive, onUnmounted, type Ref } from 'vue'
import { productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { resolveCopyTargetRole } from './bomTypes'
import type { BomSearchProduct, BomPreviewStats, ProgressState, Role } from './bomTypes'

interface UseBomCopyDialogDeps {
  /** 当前编辑 BOM 的产品 ID */
  currentProductId: Ref<number | null>
  /** 复制完成后重新加载 BOM 数据的回调 */
  reloadBom: (productId: number) => Promise<void>
  /** 当前选中的角色；null = 默认 BOM 作用域，复制物料将归属到该角色 */
  selectedRole: Ref<Role | null>
  /** 复制成功后按 id 回选目标角色（新建角色落库后 id 会变） */
  selectRoleById: (roleId: number) => void
}

/**
 * 复制 BOM 对话框（搜索源产品 → 预览 → 确认复制）
 * 从 useProductListActions 抽离，专注于对话框内的交互流程。
 */
export function useBomCopyDialog({ currentProductId, reloadBom, selectedRole, selectRoleById }: UseBomCopyDialogDeps) {
  const copyBomDialogVisible = ref(false)
  const copyBomSearchKeyword = ref('')
  const copyBomProducts = ref<BomSearchProduct[]>([])
  const copyBomSourceProductId = ref<number | null>(null)
  const copyBomPreview = ref<BomPreviewStats | null>(null)
  const copyBomOverwrite = ref(false)
  const copyBomProgress = reactive<ProgressState>({ visible: false, percent: 0, text: '' })
  const _pendingTimeouts = new Set<ReturnType<typeof setTimeout>>()
  // 组件卸载时清理所有待处理定时器
  onUnmounted(() => {
    _pendingTimeouts.forEach(clearTimeout)
    _pendingTimeouts.clear()
  })

  async function searchProductForCopy() {
    const keyword = copyBomSearchKeyword.value.trim()
    if (!keyword) { showToast('请输入产品名称或条码进行搜索', 'warning'); return }
    try {
      const res = (await productApi.searchProductsForBom(keyword)) as unknown as { success: boolean; products?: BomSearchProduct[] }
      if (res.success && res.products && res.products.length > 0) {
        copyBomProducts.value = res.products
        copyBomPreview.value = null
        copyBomSourceProductId.value = null
      } else {
        copyBomProducts.value = []
        showToast('未找到匹配的产品', 'warning')
      }
    } catch { showToast('搜索产品失败', 'error') }
  }

  async function selectCopyBomProduct(product: BomSearchProduct) {
    if (!product.has_bom) { showToast('该产品没有配置BOM表，请选择其他产品', 'warning'); return }
    copyBomSourceProductId.value = product.id
    copyBomPreview.value = null
    try {
      const res = (await productApi.bomPreview(product.id)) as { success: boolean; material_count?: number; role_count?: number; bom?: { fabric?: unknown[]; filling?: unknown[]; accessory?: unknown[]; packaging?: unknown[] } }
      if (res.success) {
        copyBomPreview.value = {
          source_name: product.name,
          source_barcode: product.barcode || '',
          material_count: res.material_count ?? 0,
          role_count: res.role_count ?? 0,
          fabric_count: res.bom?.fabric?.length || 0,
          filling_count: res.bom?.filling?.length || 0,
          accessory_count: (res.bom?.accessory?.length || 0) + (res.bom?.packaging?.length || 0),
        }
      }
    } catch { showToast('加载BOM预览失败', 'error') }
  }

  async function confirmCopyBom() {
    if (!copyBomSourceProductId.value) return
    // 解析复制归属角色：未保存的新角色按名称交给后端查找或新建，无需先保存
    const target = resolveCopyTargetRole(selectedRole.value)
    if (!target.ok) {
      showToast(target.message, 'warning')
      return
    }
    copyBomProgress.visible = true; copyBomProgress.percent = 0; copyBomProgress.text = '准备复制...'
    try {
      copyBomProgress.percent = 30; copyBomProgress.text = '正在复制BOM表...'
      // 角色模式下 overwrite 仅作用于目标角色（后端已按 role_id 收敛删除范围）
      const res = (await productApi.copyBom(
        currentProductId.value!, copyBomSourceProductId.value, copyBomOverwrite.value, target.roleId, target.roleName ?? null,
      )) as { success: boolean; error?: string; target_role?: { id: number; name: string } }
      if (res.success) {
        copyBomProgress.percent = 100; copyBomProgress.text = '复制成功！'
        const id = setTimeout(async () => {
          _pendingTimeouts.delete(id)
          copyBomProgress.visible = false
          copyBomDialogVisible.value = false
          if (currentProductId.value) await reloadBom(currentProductId.value)
          // reload 会把选中项重置为第一个角色，需回选到本次复制目标角色
          if (res.target_role?.id != null) selectRoleById(res.target_role.id)
        }, 500)
        _pendingTimeouts.add(id)
      } else {
        copyBomProgress.visible = false
        showToast(res.error || '复制失败', 'error')
      }
    } catch { copyBomProgress.visible = false; showToast('复制失败', 'error') }
  }

  return {
    copyBomDialogVisible,
    copyBomSearchKeyword,
    copyBomProducts,
    copyBomSourceProductId,
    copyBomPreview,
    copyBomOverwrite,
    copyBomProgress,
    searchProductForCopy,
    selectCopyBomProduct,
    confirmCopyBom,
  }
}

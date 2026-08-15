import { ref, reactive, computed } from 'vue'
import { productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { BomItem, BomCategory, ConfirmDialogLike } from './bomTypes'
import { useBomQuickCopy } from './useBomQuickCopy'
import { useBomCopyDialog } from './useBomCopyDialog'

interface ProductLike {
  id: number
  name: string
}

/**
 * 产品列表中 BOM 相关操作的统一入口。
 *
 * 本 composable 负责 BOM 编辑模态框的状态管理；
 * 快速复制（useBomQuickCopy）与复制对话框（useBomCopyDialog）已抽离为独立 composable。
 */
export function useProductListActions(confirmDialog: ConfirmDialogLike) {
  // ===== BOM模态框 =====
  const bomDialogVisible = ref(false)
  const bomProductName = ref('')
  const currentProductId = ref<number | null>(null)
  const currentBomCategory = ref<BomCategory>('fabric')

  const bomTabs = [
    { key: 'fabric' as const, label: '面料类', icon: 'fas fa-scroll' },
    { key: 'filling' as const, label: '填充类', icon: 'fas fa-cloud' },
    { key: 'accessory' as const, label: '辅料类', icon: 'fas fa-puzzle-piece' },
  ]

  const bomData = reactive<{ fabric: BomItem[]; filling: BomItem[]; accessory: BomItem[] }>({
    fabric: [],
    filling: [],
    accessory: [],
  })

  const currentBomItems = computed(() => bomData[currentBomCategory.value])
  const currentBomTabLabel = computed(() => bomTabs.find(tab => tab.key === currentBomCategory.value)?.label || '')

  function switchBomTab(category: BomCategory) {
    currentBomCategory.value = category
  }

  async function openBomModal(row: ProductLike) {
    currentProductId.value = row.id
    bomProductName.value = row.name
    bomDialogVisible.value = true
    currentBomCategory.value = 'fabric'
    await loadBomData(row.id)
  }

  async function loadBomData(productId: number) {
    bomData.fabric = []
    bomData.filling = []
    bomData.accessory = []
    try {
      const res = (await productApi.loadBom(productId)) as { success: boolean; materials?: unknown[] }
      if (res.success) {
        const materialsList = res.materials || []
        const grouped: { fabric: BomItem[]; filling: BomItem[]; accessory: BomItem[] } = { fabric: [], filling: [], accessory: [] }
        materialsList.forEach((item: any) => {
          const category = item.category || 'accessory'
          if (category === 'packaging') return // 包装类不在BOM配置中管理
          if (grouped[category as keyof typeof grouped]) {
            grouped[category as keyof typeof grouped].push({
              id: item.id,
              name: item.material_name || item.name || '',
              specification: item.specification || '',
              unit: item.unit || '码',
              supplier_id: item.supplier_id || null,
              supplier_name: item.supplier_name || '',
              usage: item.unit_usage || item.quantity || 1,
              remark: item.remark || '',
              category: category,
            })
          }
        })
        bomData.fabric = grouped.fabric
        bomData.filling = grouped.filling
        bomData.accessory = grouped.accessory
      }
    } catch (error) {
      console.error('加载BOM数据失败:', error)
      showToast('加载BOM数据失败', 'error')
    }
  }

  function addBomItem() {
    // 填充类每产品仅支持一条，已有数据时禁止再添加
    if (currentBomCategory.value === 'filling' && bomData.filling.length >= 1) {
      showToast('填充类物料每产品仅支持一条', 'warning')
      return
    }
    bomData[currentBomCategory.value].push({
      name: '',
      specification: '',
      unit: currentBomCategory.value === 'filling' ? '克' : '码',
      supplier_name: '',
      usage: 1,
      remark: '',
      category: currentBomCategory.value,
    })
  }

  async function deleteBomItem(index: number) {
    const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
    if (!ok) return
    bomData[currentBomCategory.value].splice(index, 1)
  }

  async function saveBom() {
    const allItems = [
      ...bomData.fabric.map(item => ({ ...item, category: 'fabric' })),
      ...bomData.filling.map(item => ({ ...item, category: 'filling' })),
      ...bomData.accessory.map(item => ({ ...item, category: item.category || 'accessory' })),
    ]
    const invalidItems = allItems.filter(item => !item.name || !item.specification || !item.unit || !item.supplier_name)
    if (invalidItems.length > 0) { showToast('请填写所有必填项（物料名称、规格型号、计量单位、默认供应商）', 'warning'); return }

    try {
      const payload = {
        fabrics: bomData.fabric.map(item => ({
          id: item.id,
          fabric_name: item.name,
          specification: item.specification,
          unit: item.unit,
          quantity: item.usage,
          supplier_id: item.supplier_id,
          supplier_name: item.supplier_name,
          remark: item.remark,
          category: 'fabric',
        })),
        filling: bomData.filling.length > 0 ? (() => {
          const filling = bomData.filling[0]!
          return {
            id: filling.id,
            cotton_usage: filling.usage,
            specification: filling.specification,
            supplier_id: filling.supplier_id,
            supplier_name: filling.supplier_name,
            unit: filling.unit,
            remark: filling.remark,
          }
        })() : null,
        accessories: bomData.accessory.map(item => ({
          id: item.id,
          accessory_name: item.name,
          specification: item.specification,
          unit: item.unit,
          quantity: item.usage,
          supplier_id: item.supplier_id,
          supplier_name: item.supplier_name,
          remark: item.remark,
          category: 'accessory',
        })),
        packagings: [],
      }
      const res = (await productApi.saveBom(currentProductId.value!, payload)) as { success: boolean; error?: string }
      if (res.success) {
        showToast('保存成功', 'success')
        bomDialogVisible.value = false
      } else {
        showToast(res.error || '保存失败', 'error')
      }
    } catch (error) {
      showToast('保存BOM失败', 'error')
    }
  }

  // ===== 快速复制 BOM（抽离至 useBomQuickCopy） =====
  const quickCopy = useBomQuickCopy({
    currentProductId,
    reloadBom: loadBomData,
  })

  // ===== 复制 BOM 对话框（抽离至 useBomCopyDialog） =====
  const copyDialog = useBomCopyDialog({
    currentProductId,
    reloadBom: loadBomData,
  })

  return {
    // BOM modal
    bomDialogVisible,
    bomProductName,
    currentProductId,
    currentBomCategory,
    bomTabs,
    currentBomItems,
    currentBomTabLabel,
    switchBomTab,
    openBomModal,
    addBomItem,
    deleteBomItem,
    saveBom,
    // Quick copy
    ...quickCopy,
    // Copy BOM dialog
    ...copyDialog,
  }
}

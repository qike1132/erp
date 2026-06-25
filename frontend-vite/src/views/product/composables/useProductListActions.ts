import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { productApi } from '@/api'
import { showToast } from '@/composables/useToast'

export interface BomItem {
  id?: number
  name: string
  specification: string
  unit: string
  supplier_id?: number | null
  supplier_name: string
  usage: number
  remark: string
  category?: string
}

interface ProductLike {
  id: number
  name: string
}

interface ConfirmDialogLike {
  confirm: (msg: string, subMsg?: string, dialogType?: 'danger' | 'warning') => Promise<boolean>
}

/**
 * 产品列表中 BOM 相关操作：BOM 配置弹窗、快速复制 BOM、复制 BOM 弹窗。
 * 抽离自 ProductListView.vue 以降低主组件复杂度。
 */
export function useProductListActions(confirmDialog: ConfirmDialogLike) {
  // ===== BOM模态框 =====
  const bomDialogVisible = ref(false)
  const bomProductName = ref('')
  const currentProductId = ref<number | null>(null)
  const currentBomCategory = ref<'fabric' | 'filling' | 'accessory'>('fabric')

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

  function switchBomTab(category: 'fabric' | 'filling' | 'accessory') {
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
      const res = (await productApi.loadBom(productId)) as any
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
    bomData[currentBomCategory.value].push({ name: '', specification: '', unit: currentBomCategory.value === 'filling' ? '克' : '码', supplier_name: '', usage: 1, remark: '', category: currentBomCategory.value })
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
          if (bomData.filling.length > 1) {
            showToast('填充类物料每产品仅支持一条，已自动取第一条', 'warning')
          }
          const filling = bomData.filling[0]
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
      const res = (await productApi.saveBom(currentProductId.value!, payload)) as any
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

  // ===== 快速复制BOM（自动补全） =====
  const quickCopyKeyword = ref('')
  const quickCopyInputRef = ref<HTMLInputElement | null>(null)
  const quickCopyLoading = ref(false)
  const autocompleteVisible = ref(false)
  const autocompleteItems = ref<any[]>([])
  const autocompleteIndex = ref(-1)
  let autocompleteTimeout: ReturnType<typeof setTimeout> | null = null
  const _pendingTimeouts = new Set<ReturnType<typeof setTimeout>>()
  let selectedSourceProductId: number | null = null
  let selectedSourceProductName: string | null = null

  const quickCopyProgress = reactive({ visible: false, percent: 0, text: '' })

  watch(quickCopyKeyword, (val) => {
    if (autocompleteTimeout) clearTimeout(autocompleteTimeout)
    if (val.trim().length < 1) { autocompleteVisible.value = false; return }
    autocompleteTimeout = setTimeout(() => searchAutocompleteProducts(val.trim()), 300)
  })

  async function searchAutocompleteProducts(keyword: string) {
    try {
      const res = (await productApi.searchProductsForBom(keyword)) as any
      autocompleteIndex.value = -1
      if (res.success && res.products?.length > 0) {
        autocompleteItems.value = res.products
        autocompleteVisible.value = true
      } else {
        autocompleteItems.value = []
        autocompleteVisible.value = true
      }
    } catch {
      autocompleteVisible.value = false
    }
  }

  function onAutocompleteKeydown(e: KeyboardEvent) {
    if (!autocompleteVisible.value || autocompleteItems.value.length === 0) {
      if (e.key === 'Enter') { e.preventDefault(); autocompleteVisible.value = false; quickCopyBom() }
      return
    }
    const items = autocompleteItems.value.filter(item => item.has_bom)
    if (e.key === 'ArrowDown') { e.preventDefault(); autocompleteIndex.value = Math.min(autocompleteIndex.value + 1, items.length - 1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); autocompleteIndex.value = Math.max(autocompleteIndex.value - 1, -1) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      if (autocompleteIndex.value >= 0 && autocompleteIndex.value < items.length) {
        selectAutocompleteItem(items[autocompleteIndex.value])
      } else { autocompleteVisible.value = false; quickCopyBom() }
    }
    else if (e.key === 'Escape') { e.preventDefault(); autocompleteVisible.value = false }
  }

  function selectAutocompleteItem(item: any) {
    if (!item.has_bom) return
    selectedSourceProductId = item.id
    selectedSourceProductName = item.name
    quickCopyKeyword.value = item.name
    autocompleteVisible.value = false
  }

  function onQuickCopyFocus() {
    if (quickCopyKeyword.value.trim() && autocompleteItems.value.length === 0) {
      searchAutocompleteProducts(quickCopyKeyword.value.trim())
    } else if (autocompleteItems.value.length > 0) {
      autocompleteVisible.value = true
    }
  }
  function hideAutocomplete() {
    const id = setTimeout(() => { autocompleteVisible.value = false; _pendingTimeouts.delete(id) }, 150)
    _pendingTimeouts.add(id)
  }

  async function quickCopyBom() {
    let sourceId = selectedSourceProductId
    let sourceName = selectedSourceProductName || ''

    if (!sourceId) {
      const keyword = quickCopyKeyword.value.trim()
      if (!keyword) { showToast('请输入产品名称或条码', 'warning'); return }

      quickCopyLoading.value = true
      quickCopyProgress.visible = true; quickCopyProgress.percent = 10; quickCopyProgress.text = '搜索产品中...'
      try {
        const res = (await productApi.searchProductsForBom(keyword)) as any
        if (!res.success || !res.products?.length) { hideQuickCopyProgress(); quickCopyLoading.value = false; showToast('未找到匹配的产品', 'warning'); return }
        const withBom = res.products.filter((product: any) => product.has_bom)
        if (!withBom.length) { hideQuickCopyProgress(); quickCopyLoading.value = false; showToast('找到产品没有配置BOM表', 'warning'); return }
        sourceId = withBom[0].id
        sourceName = withBom[0].name
      } catch { hideQuickCopyProgress(); quickCopyLoading.value = false; showToast('搜索失败', 'error'); return }
    }

    quickCopyProgress.percent = 40; quickCopyProgress.text = `正在从 "${sourceName}" 复制BOM...`

    try {
      quickCopyProgress.percent = 70; quickCopyProgress.text = '执行复制...'
      const res = (await productApi.copyBom(currentProductId.value!, sourceId!, true)) as any
      if (res.success) {
        quickCopyProgress.percent = 100; quickCopyProgress.text = '复制成功！'
        const id = setTimeout(() => {
          _pendingTimeouts.delete(id)
          hideQuickCopyProgress()
          quickCopyLoading.value = false
          loadBomData(currentProductId.value!)
          quickCopyKeyword.value = ''
          selectedSourceProductId = null
          selectedSourceProductName = null
        }, 500)
        _pendingTimeouts.add(id)
      } else {
        hideQuickCopyProgress(); quickCopyLoading.value = false
        showToast(res.error || '复制失败', 'error')
      }
    } catch { hideQuickCopyProgress(); quickCopyLoading.value = false; showToast('复制失败', 'error') }
  }

  function hideQuickCopyProgress() { quickCopyProgress.visible = false }

  // 点击外部关闭自动补全
  function onDocClick(e: MouseEvent) {
    if (autocompleteVisible.value) {
      const target = e.target as HTMLElement
      if (!target.closest('.autocomplete-wrapper')) autocompleteVisible.value = false
    }
  }
  onMounted(() => document.addEventListener('click', onDocClick))
  onUnmounted(() => {
    document.removeEventListener('click', onDocClick)
    if (autocompleteTimeout) clearTimeout(autocompleteTimeout)
    _pendingTimeouts.forEach(clearTimeout)
  })

  // ===== 复制BOM模态框 =====
  const copyBomDialogVisible = ref(false)
  const copyBomSearchKeyword = ref('')
  const copyBomProducts = ref<any[]>([])
  const copyBomSourceProductId = ref<number | null>(null)
  const copyBomPreview = ref<any>(null)
  const copyBomOverwrite = ref(false)
  const copyBomProgress = reactive({ visible: false, percent: 0, text: '' })

  async function searchProductForCopy() {
    const keyword = copyBomSearchKeyword.value.trim()
    if (!keyword) { showToast('请输入产品名称或条码进行搜索', 'warning'); return }
    try {
      const res = (await productApi.searchProductsForBom(keyword)) as any
      if (res.success && res.products?.length > 0) {
        copyBomProducts.value = res.products
        copyBomPreview.value = null
        copyBomSourceProductId.value = null
      } else {
        copyBomProducts.value = []
        showToast('未找到匹配的产品', 'warning')
      }
    } catch { showToast('搜索产品失败', 'error') }
  }

  async function selectCopyBomProduct(product: any) {
    if (!product.has_bom) { showToast('该产品没有配置BOM表，请选择其他产品', 'warning'); return }
    copyBomSourceProductId.value = product.id
    copyBomPreview.value = null
    try {
      const res = (await productApi.bomPreview(product.id)) as any
      if (res.success) {
        copyBomPreview.value = {
          source_name: product.name,
          source_barcode: product.barcode || '',
          material_count: res.material_count,
          fabric_count: res.bom?.fabric?.length || 0,
          filling_count: res.bom?.filling?.length || 0,
          accessory_count: (res.bom?.accessory?.length || 0) + (res.bom?.packaging?.length || 0),
        }
      }
    } catch { showToast('加载BOM预览失败', 'error') }
  }

  async function confirmCopyBom() {
    if (!copyBomSourceProductId.value) return
    copyBomProgress.visible = true; copyBomProgress.percent = 0; copyBomProgress.text = '准备复制...'
    try {
      copyBomProgress.percent = 30; copyBomProgress.text = '正在复制BOM表...'
      const res = (await productApi.copyBom(currentProductId.value!, copyBomSourceProductId.value, copyBomOverwrite.value)) as any
      if (res.success) {
        copyBomProgress.percent = 100; copyBomProgress.text = '复制成功！'
        const id = setTimeout(() => {
          _pendingTimeouts.delete(id)
          copyBomProgress.visible = false
          copyBomDialogVisible.value = false
          loadBomData(currentProductId.value!)
        }, 500)
        _pendingTimeouts.add(id)
      } else {
        copyBomProgress.visible = false
        showToast(res.error || '复制失败', 'error')
      }
    } catch { copyBomProgress.visible = false; showToast('复制失败', 'error') }
  }

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
    quickCopyKeyword,
    quickCopyInputRef,
    quickCopyLoading,
    autocompleteVisible,
    autocompleteItems,
    autocompleteIndex,
    quickCopyProgress,
    onAutocompleteKeydown,
    selectAutocompleteItem,
    onQuickCopyFocus,
    hideAutocomplete,
    quickCopyBom,
    // Copy BOM dialog
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

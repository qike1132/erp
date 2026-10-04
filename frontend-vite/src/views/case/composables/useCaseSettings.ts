import { ref, computed, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseItem, CaseProduct } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import { CASE_QUERY_KEYS } from './useCaseStockWorkbench'

export type { CaseProduct }

/** 有配件 / 无配件 分段筛选 */
export type PartsFilter = 'all' | 'yes' | 'no'

/** 一次加载的产品数上限（与物料用量计算 ProductSelectColumn 同口径） */
const PRODUCT_CAP = 200

/**
 * 皮套设置：**以产品为根**。
 * 数据源 = `GET /cases/products`（全部产品 + 各自配件数），一次载入后本地按
 * 关键词 + 有/无配件过滤；选中产品时经 `POST /cases/for-product` 取其主件（不存在则自动建）
 * 与配件清单，在右栏维护。过滤逻辑照抄物料用量计算的 `useProductPicker`。
 */
export function useCaseSettings() {
  const queryClient = useQueryClient()

  const keyword = ref('')
  const partsFilter = ref<PartsFilter>('all')

  // 击键防抖：keyword 直接进 queryKey（服务端 search），不防抖就是逐键打接口。
  const committedKeyword = ref('')
  let kwTimer: ReturnType<typeof setTimeout> | null = null
  watch(keyword, (v) => {
    if (kwTimer) clearTimeout(kwTimer)
    kwTimer = setTimeout(() => {
      committedKeyword.value = v.trim()
    }, 300)
  })

  // 空关键词：一次拉前 200 个做本地过滤（对齐物料用量计算的 ProductSelectColumn）。
  // 有关键词：**透传服务端 search** —— 只过滤本地那 200 条会让第 201 个及之后的产品
  // 搜不出来也选不中，而「如未找到请用上方搜索」的提示反而误导（后端本就支持 search）。
  const { data, isLoading } = useQuery({
    queryKey: ['case-products', committedKeyword.value],
    queryFn: () =>
      caseApi.products({
        page: 1,
        per_page: PRODUCT_CAP,
        search: committedKeyword.value || undefined,
      }),
    staleTime: 30_000,
  })

  const products = computed<CaseProduct[]>(() => data.value?.products ?? [])
  const capped = computed(() => products.value.length >= PRODUCT_CAP)

  const filtered = computed<CaseProduct[]>(() => {
    let list = products.value
    if (partsFilter.value === 'yes') list = list.filter((p) => p.has_parts)
    else if (partsFilter.value === 'no') list = list.filter((p) => !p.has_parts)
    return list
  })

  // ---- 选中产品的皮套树（主件 + 配件）----
  const selectedProductId = ref<number | null>(null)
  const selectedMain = ref<CaseItem | null>(null)
  const selectedParts = ref<CaseItem[]>([])
  const loadingTree = ref(false)
  // 请求序号：快速连选产品时丢弃过期响应，否则会把配件挂到**错误的主件**下
  // （addPart 用 selectedMain.value.id 作 parent_id → 写库错误）。第二轮审计 5b0eb728
  // 加过，84005549 重写本文件时被删 —— 这次一次列出 200 行、单击即发请求，更易触发。
  let loadSeq = 0

  async function loadTree(id: number) {
    const tree = await caseApi.forProduct(id)
    return tree
  }

  async function selectProduct(id: number) {
    if (selectedProductId.value === id && selectedMain.value) return
    const seq = ++loadSeq
    selectedProductId.value = id
    selectedMain.value = null
    selectedParts.value = []
    loadingTree.value = true
    try {
      const tree = await loadTree(id)
      if (seq !== loadSeq) return  // 已被更新的选择作废
      selectedMain.value = tree.main
      selectedParts.value = tree.parts ?? []
    } catch (e: unknown) {
      if (seq !== loadSeq) return
      selectedMain.value = null
      selectedParts.value = []
      showToast(getErrorMessage(e, '加载该产品的皮套失败'), 'error')
    } finally {
      if (seq === loadSeq) loadingTree.value = false
    }
  }

  const saving = ref(false)

  /** 配件增删改后：刷新当前树 + 失效产品列表（配件数变了）与库存相关查询 */
  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['case-products'] })
    for (const key of CASE_QUERY_KEYS) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }

  async function addPart(name: string) {
    const n = name.trim()
    if (!n || !selectedMain.value) {
      showToast('请填配件名称', 'warning')
      return
    }
    saving.value = true
    try {
      await caseApi.createItem({ name: n, parent_id: selectedMain.value.id })
      showToast('已添加配件', 'success')
      if (selectedProductId.value != null) await loadTree(selectedProductId.value)
      invalidate()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '添加失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  async function savePart(id: number, name: string) {
    if (!name.trim()) {
      showToast('配件名称不能为空', 'warning')
      return
    }
    saving.value = true
    try {
      await caseApi.updateItem(id, { name: name.trim() })
      showToast('已保存', 'success')
      if (selectedProductId.value != null) await loadTree(selectedProductId.value)
      invalidate()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '保存失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  async function removePart(id: number) {
    saving.value = true
    try {
      await caseApi.deleteItem(id)
      showToast('已删除', 'success')
      if (selectedProductId.value != null) await loadTree(selectedProductId.value)
      invalidate()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '删除失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  return {
    keyword,
    partsFilter,
    products,
    filtered,
    capped,
    isLoading,
    selectedProductId,
    selectedMain,
    selectedParts,
    loadingTree,
    selectProduct,
    saving,
    addPart,
    savePart,
    removePart,
  }
}

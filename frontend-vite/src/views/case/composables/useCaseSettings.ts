import { ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import { useCaseOptions } from './useCaseOptions'
import type { CaseItem } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import { CASE_QUERY_KEYS } from './useCaseStockWorkbench'

/** 可编辑的配件行（名称 + 配比） */
export interface EditablePart {
  id: number
  name: string
  qtyPerSet: number
}

/**
 * 皮套设置：按产品取皮套主件，维护其配件（增/改名/配比/删）。
 */
export function useCaseSettings() {
  const queryClient = useQueryClient()
  const { searchProducts, fetchCaseTree } = useCaseOptions()

  const productQuery = ref('')
  const main = ref<CaseItem | null>(null)
  const parts = ref<CaseItem[]>([])
  const rows = ref<EditablePart[]>([])
  const loading = ref(false)
  const saving = ref(false)

  watch(parts, (list) => {
    rows.value = list.map((p) => ({ id: p.id, name: p.name, qtyPerSet: p.qty_per_set }))
  })

  // 请求序号：快速连选产品时丢弃过期响应，否则会把配件挂到**错误的主件**下
  // （addPart 用 main.value.id 作 parent_id → 写库错误）。
  let loadSeq = 0

  async function load(productId: number, name: string) {
    const seq = ++loadSeq
    productQuery.value = name
    loading.value = true
    try {
      const tree = await fetchCaseTree(productId)
      if (seq !== loadSeq) return  // 已被更新的选择作废
      main.value = tree?.main ?? null
      parts.value = tree?.parts ?? []
    } finally {
      if (seq === loadSeq) loading.value = false
    }
  }

  function selectProduct(p: { id: number; name: string }) {
    void load(p.id, p.name)
  }

  /** 用主件的 product_id 重新拉取（增删改后用） */
  async function reload() {
    if (main.value?.product_id) await load(main.value.product_id, main.value.name)
  }

  function invalidate() {
    for (const key of CASE_QUERY_KEYS) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }

  async function addPart(name: string, qtyPerSet: number) {
    const n = name.trim()
    if (!n || !main.value) {
      showToast('请填配件名称', 'warning')
      return
    }
    saving.value = true
    try {
      await caseApi.createItem({ name: n, parent_id: main.value.id, qty_per_set: qtyPerSet })
      showToast('已添加配件', 'success')
      await reload()
      invalidate()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '添加失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  async function savePart(row: EditablePart) {
    if (!row.name.trim()) {
      showToast('配件名称不能为空', 'warning')
      return
    }
    saving.value = true
    try {
      await caseApi.updateItem(row.id, { name: row.name.trim(), qty_per_set: row.qtyPerSet })
      showToast('已保存', 'success')
      await reload()  // 必须回读：rows 由 watch(parts) 派生，invalidate() 触及不到它，
      invalidate()    // 否则 chip 上仍显示旧名称/旧配比，用户以为没保存成功
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '保存失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  async function removePart(row: EditablePart) {
    saving.value = true
    try {
      await caseApi.deleteItem(row.id)
      showToast('已删除', 'success')
      await reload()
      invalidate()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '删除失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  return {
    productQuery,
    searchProducts,
    main,
    parts,
    rows,
    loading,
    saving,
    selectProduct,
    addPart,
    savePart,
    removePart,
  }
}

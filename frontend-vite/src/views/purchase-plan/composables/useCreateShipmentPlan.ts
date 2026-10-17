// 出货计划创建表单的状态 / 产品搜索建议 / 校验 / 提交逻辑（从 CreateShipmentPlanDialog.vue 抽出，行为不变）
import { ref, reactive, computed, watch, onUnmounted, type Ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { planApi, customerApi } from '@/api'
import { auxApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'

// 单条出货明细行
export interface DetailLine {
  customer_id: string
  product_name: string
  product_id: number
  barcode: string
  plan_date: string
  quantity: number | null
  _showSuggest: boolean
}

// 产品搜索建议项（/aux/product-search 返回）
export interface ProductSuggestion {
  id: number
  name: string
  barcode?: string
  current_stock?: number | null
}

// 客户名条目（兼容 names 数组与字符串混合返回）
interface CustomerNameItem {
  id?: number
  name?: string
}

export function useCreateShipmentPlan(open: Ref<boolean>, onCreated: () => void) {
  const ym = (() => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}` })()

  const form = reactive({
    details: [
      { customer_id: '', product_name: '', product_id: 0, barcode: '', plan_date: '', quantity: null, _showSuggest: false },
    ] as DetailLine[],
  })

  // 每行对应的产品建议列表（下标为明细行索引）
  const productSuggestions = reactive<Record<number, ProductSuggestion[]>>({})
  let _searchTimer: ReturnType<typeof setTimeout> | null = null
  onUnmounted(() => { if (_searchTimer) clearTimeout(_searchTimer) })

  const submitting = ref(false)
  const errorMsg = ref('')

  watch(open, (val) => {
    if (val) {
      form.details = [{ customer_id: '', product_name: '', product_id: 0, barcode: '', plan_date: '', quantity: null, _showSuggest: false }]
      errorMsg.value = ''
    }
  })

  const { data: namesData } = useQuery({
    queryKey: ['customer-active-names'],
    queryFn: async () => {
      const r = (await customerApi.activeNames()) as unknown as (CustomerNameItem[] & { names?: CustomerNameItem[] })
      return r.names ?? r ?? []
    },
    staleTime: 60_000,
  })

  const customerMap = computed(() => {
    const arr = Array.isArray(namesData.value) ? namesData.value : []
    const map = new Map<number, string>()
    for (const c of arr) {
      map.set(Number(c.id ?? 0), c.name ?? String(c))
    }
    return map
  })

  const customerOptions = computed(() => {
    const arr = Array.isArray(namesData.value) ? namesData.value : []
    return arr.map((c) => ({ value: String(c.id ?? ''), label: c.name ?? String(c) }))
  })

  function addDetail() {
    form.details.push({ customer_id: '', product_name: '', product_id: 0, barcode: '', plan_date: '', quantity: null, _showSuggest: false })
  }

  function removeDetail(idx: number) {
    form.details.splice(idx, 1)
    // F-FE-DESK-CORE-04：productSuggestions 以行下标为键，splice 收缩后所有
    // 后续行下标 -1，必须整体前移——否则剩余行读到的是「别的行」遗留的建议，
    // 点一下就落成错误 product_id。
    delete productSuggestions[idx]
    const keys = Object.keys(productSuggestions).map(Number).sort((a, b) => a - b)
    for (const k of keys) {
      if (k > idx) {
        productSuggestions[k - 1] = productSuggestions[k] ?? []
        delete productSuggestions[k]
      }
    }
  }

  async function searchProducts(q: string): Promise<ProductSuggestion[]> {
    if (!q.trim()) return []
    try {
    const d = await auxApi.productSearch(q) as ProductSuggestion[]
      return Array.isArray(d) ? d : []
    } catch {
      return []
    }
  }

  function onProductInput(idx: number) {
    const d = form.details[idx]
    if (!d) return
    const kw = d.product_name.trim()
    d.product_id = 0
    if (_searchTimer) clearTimeout(_searchTimer)
    if (!kw) {
      productSuggestions[idx] = []
      d._showSuggest = false
      return
    }
    _searchTimer = setTimeout(async () => {
      const list = await searchProducts(kw)
      productSuggestions[idx] = list.slice(0, 10)
      const d2 = form.details[idx]
      if (d2) d2._showSuggest = list.length > 0
    }, 300)
  }

  function onProductFocus(idx: number) {
    const d = form.details[idx]
    if (!d) return
    const kw = d.product_name.trim()
    if (kw && !(productSuggestions[idx]?.length)) {
      searchProducts(kw).then(r => {
        productSuggestions[idx] = r.slice(0, 10)
        const d2 = form.details[idx]
        if (d2) d2._showSuggest = r.length > 0
      })
    } else if (productSuggestions[idx]?.length) {
      d._showSuggest = true
    }
  }

  function onProductBlur(idx: number) {
    setTimeout(() => {
      const d = form.details[idx]
      if (d) d._showSuggest = false
    }, 150)
  }

  function selectProduct(idx: number, p: ProductSuggestion) {
    const d = form.details[idx]
    if (!d) return
    d.product_name = p.name || ''
    d.product_id = p.id || 0
    d.barcode = p.barcode || ''
    d._showSuggest = false
    productSuggestions[idx] = []
  }

  function validate(): string | null {
    for (let i = 0; i < form.details.length; i++) {
      const d = form.details[i]
      if (!d) return `第 ${i + 1} 行：数据不完整`
      if (!d.customer_id) return `第 ${i + 1} 行：请选择客户`
      if (!d.product_name.trim()) return `第 ${i + 1} 行：产品名称不能为空`
      // F-FE-DESK-CORE-04：product_id=0（未从下拉选择）原先直接落 payload，
      // 后端只验「产品存在」验不出「选错了产品」——必须显式选择。
      if (!d.product_id) return `第 ${i + 1} 行：请从下拉中选择产品`
      if (!d.plan_date) return `第 ${i + 1} 行：请选择出货日期`
      if (!d.quantity || d.quantity <= 0) return `第 ${i + 1} 行：数量必须大于 0`
      if (!Number.isInteger(d.quantity)) return `第 ${i + 1} 行：数量必须为整数`
    }

    return null
  }

  async function handleSubmit() {
    const err = validate()
    if (err) { errorMsg.value = err; return }
    errorMsg.value = ''

    submitting.value = true
    try {
      // 按客户分组提交
      const byCustomer = new Map<number, DetailLine[]>()
      for (const d of form.details) {
        const cid = Number(d.customer_id)
        if (!byCustomer.has(cid)) byCustomer.set(cid, [])
        byCustomer.get(cid)!.push(d)
      }

      for (const [cid, lines] of byCustomer) {
        const cname = customerMap.value.get(cid) || ''
        const firstLine = lines[0]
        const planMonth = firstLine?.plan_date ? firstLine.plan_date.substring(0, 7) : ym

        const payload = {
          customer_id: cid,
          customer_name: cname,
          plan_month: planMonth,
          details: lines.map(d => ({
            product_id: d.product_id || 0,
            product_name: d.product_name.trim(),
            barcode: d.barcode || '',
            plan_date: d.plan_date,
            quantity: Number(d.quantity),
            remark: '',
          })),
        }

        await planApi.create(payload)
      }

      showToast('出货计划创建成功', 'success')
      onCreated()
    } catch (err: unknown) {
      const detail = getErrorMessage(err, '创建失败，请重试')
      errorMsg.value = detail
      showToast(errorMsg.value, 'error')
    } finally {
      submitting.value = false
    }
  }

  return {
    form,
    productSuggestions,
    submitting,
    errorMsg,
    customerOptions,
    addDetail,
    removeDetail,
    onProductInput,
    onProductFocus,
    onProductBlur,
    selectProduct,
    handleSubmit,
  }
}

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

/**
 * 提交结果回调（H6，2026-10-26）：
 * - `onCreated`：**全部成功**才触发（调用方据此关闭对话框）；
 * - `onSucceeded`：只要有成功提交的分组就触发（调用方只刷新数据、不关闭对话框）。
 *
 * 原先只有一个 `onCreated`，且无条件调用——部分失败甚至全部失败时对话框照样关闭、
 * 下次打开又重置明细，用户刚填的草稿直接丢失。
 */
export function useCreateShipmentPlan(
  open: Ref<boolean>,
  onCreated: () => void,
  options: { onSucceeded?: () => void } = {},
) {
  const ym = (() => { const n = new Date(); return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}` })()

  const form = reactive({
    details: [
      { customer_id: '', product_name: '', product_id: 0, barcode: '', plan_date: '', quantity: null, _showSuggest: false },
    ] as DetailLine[],
  })

  // 每行对应的产品建议列表（下标为明细行索引）
  const productSuggestions = reactive<Record<number, ProductSuggestion[]>>({})
  // M6（2026-10-26）：每行一个请求序号。同一行连打关键字时，先发的慢响应
  // 可能后到并覆盖新关键字的结果（用户选中一串与输入框内容不符的产品）。
  // 序号 + 关键字快照双保险：响应回来时不匹配就整包丢弃。
  // 序号来自**全表单单调递增**计数器：行下标会被 splice 复用，若按行清零重置，
  // 旧的在途请求可能拿到与新请求相同的序号（ABA），过滤就失效。
  const _suggestSeq = new Map<number, number>()
  let _suggestCounter = 0
  let _searchTimer: ReturnType<typeof setTimeout> | null = null
  onUnmounted(() => { if (_searchTimer) clearTimeout(_searchTimer) })

  function _nextSuggestSeq(idx: number): number {
    _suggestCounter += 1
    _suggestSeq.set(idx, _suggestCounter)
    return _suggestCounter
  }

  const submitting = ref(false)
  const errorMsg = ref('')

  watch(open, (val) => {
    if (val) {
      form.details = [{ customer_id: '', product_name: '', product_id: 0, barcode: '', plan_date: '', quantity: null, _showSuggest: false }]
      // 打开即作废旧行建议（行下标被复用，旧响应不得落到新表单上）
      _suggestSeq.clear()
      for (const k of Object.keys(productSuggestions)) delete productSuggestions[Number(k)]
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
    // 行下标整体位移：在途请求的序号会随 splice 落到别的行上，但全局计数器
    // 保证「新请求的序号一定更大」，旧响应回来时序号必然不匹配而被丢弃。
    _suggestSeq.clear()
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
    // 立刻作废该行所有在途请求：输入变了以后，旧关键字的响应一律不许落盘
    const seq = _nextSuggestSeq(idx)
    if (!kw) {
      productSuggestions[idx] = []
      d._showSuggest = false
      return
    }
    _searchTimer = setTimeout(async () => {
      const list = await searchProducts(kw)
      // M6：序号或关键字任一不匹配即丢弃（行被删/输入又变了/请求乱序返回）
      if (_suggestSeq.get(idx) !== seq) return
      const d2 = form.details[idx]
      if (!d2 || d2.product_name.trim() !== kw) return
      productSuggestions[idx] = list.slice(0, 10)
      d2._showSuggest = list.length > 0
    }, 300)
  }

  function onProductFocus(idx: number) {
    const d = form.details[idx]
    if (!d) return
    const kw = d.product_name.trim()
    if (kw && !(productSuggestions[idx]?.length)) {
      const seq = _nextSuggestSeq(idx)
      searchProducts(kw).then(r => {
        if (_suggestSeq.get(idx) !== seq) return
        const d2 = form.details[idx]
        if (!d2 || d2.product_name.trim() !== kw) return
        productSuggestions[idx] = r.slice(0, 10)
        d2._showSuggest = r.length > 0
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
    // 选中即定稿：此后任何在途搜索响应都不得再改这一行的建议列表
    _nextSuggestSeq(idx)
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

  /** 明细行的归属月份（YYYY-MM）；日期非法时退回当前月。 */
  function _monthOf(dateStr: string): string {
    const m = /^(\d{4})-(\d{2})/.exec(dateStr || '')
    return m ? `${m[1]}-${m[2]}` : ym
  }

  function _groupKey(d: DetailLine): string {
    return `${Number(d.customer_id)}|${_monthOf(d.plan_date)}`
  }

  function _invalidateAllSuggestions() {
    _suggestSeq.clear()
    for (const k of Object.keys(productSuggestions)) delete productSuggestions[Number(k)]
  }

  async function handleSubmit() {
    const err = validate()
    if (err) { errorMsg.value = err; return }
    errorMsg.value = ''

    submitting.value = true
    try {
      // H5（2026-10-26）：必须按 (客户, 月份) 分组，而不是只按客户。
      // 后端 `_validate_details_cross_month` 逐行拒绝与 plan_month 不一致的明细，
      // 而旧实现从**首行**推导整个客户的 plan_month——同客户跨月时必然被拒，
      // 且错误信息指向「明细与计划月份不一致」，用户无从修正。
      const groups = new Map<string, { cid: number; month: string; lines: DetailLine[] }>()
      for (const d of form.details) {
        const key = _groupKey(d)
        const g = groups.get(key)
        if (g) {
          g.lines.push(d)
        } else {
          groups.set(key, { cid: Number(d.customer_id), month: _monthOf(d.plan_date), lines: [d] })
        }
      }

      // F1a-03（2026-10-24 审计）：逐分组提交并收集成败——原先任一客户失败
      // 整批进 catch，重试必被已建客户的 409 阻断（重试必败态），且无逐户反馈。
      const failures: string[] = []
      const succeededKeys = new Set<string>()
      for (const [key, g] of groups) {
        const cname = customerMap.value.get(g.cid) || ''

        const payload = {
          customer_id: g.cid,
          customer_name: cname,
          plan_month: g.month,
          details: g.lines.map(d => ({
            product_id: d.product_id || 0,
            product_name: d.product_name.trim(),
            barcode: d.barcode || '',
            plan_date: d.plan_date,
            quantity: Number(d.quantity),
            remark: '',
          })),
        }

        try {
          await planApi.create(payload)
          succeededKeys.add(key)
        } catch (e: unknown) {
          const detail = (e as { response?: { data?: { detail?: string } } })
            ?.response?.data?.detail
          const who = cname || `客户${g.cid}`
          failures.push(`${who}（${g.month}）：${detail || '创建失败'}`)
        }
      }

      const succeededCount = succeededKeys.size
      if (failures.length === 0) {
        showToast('出货计划创建成功', 'success')
        options.onSucceeded?.()
        onCreated()
        return
      }

      // H6（2026-10-26）：失败不得关闭对话框。
      //  - 部分成功：刷新数据（让已创建的可见），并从草稿里移除已成功的分组，
      //    只保留失败项供重试（重试不会再触发已建分组的 409）；
      //  - 全部失败：草稿原样保留。
      if (succeededCount > 0) {
        options.onSucceeded?.()
        form.details = form.details.filter(d => !succeededKeys.has(_groupKey(d)))
        _invalidateAllSuggestions()
        if (form.details.length === 0) addDetail()
        errorMsg.value = `部分分组创建失败（${succeededCount} 成功 / ${failures.length} 失败，`
          + `失败项已保留在表单中）：` + failures.join('；')
      } else {
        errorMsg.value = `创建失败（草稿已保留，可直接重试）：${failures.join('；')}`
      }
      showToast(errorMsg.value, 'error')
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

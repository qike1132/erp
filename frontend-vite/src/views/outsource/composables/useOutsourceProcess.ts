import { computed, reactive, ref, toRef, type Ref } from 'vue'
import { outsourceApi } from '@/api/outsource'
import type { OrderOutsourceProcess, OutsourceProcessFlow } from '@/api/outsource'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/composables/useToast'
import type { OutsourceOrderRow } from '@/views/outsource/composables/useOutsourceOrders'

/** 工序分组（按 SKU / order_item_id） */
export interface ProcessGroup {
  itemId: number | null
  skuName: string
  skuQty: number
  processes: OrderOutsourceProcess[]
}

/** 订单外发工序弹窗的业务逻辑 */
export function useOutsourceProcess(detailDataProp: Ref<OutsourceOrderRow | null>, emit: (event: 'refresh') => void) {
  const authStore = useAuthStore()
  /** 发货权限点：外协方账号授权（替代原先按用户名 == '贝乐' 的硬编码判断） */
  const canShip = computed(() => authStore.hasPermission('outsource_ship'))
  /** 收货权限点：收货账号授权（替代原先按用户名 == '贝乐' 的硬编码判断） */
  const canReceive = computed(() => authStore.hasPermission('outsource_receive'))

  const processes = ref<OrderOutsourceProcess[]>([])
  const loadingProcesses = ref(false)
  /** 外发工序流水（发货/收货记录，台账用） */
  const flows = ref<OutsourceProcessFlow[]>([])

  /** 每道工序可编辑的本批发货数量草稿（缺省=剩余待发） */
  const shipQtyDrafts = reactive<Record<number, string>>({})
  /** 每道工序可编辑的本批收货数量草稿（缺省=剩余待收） */
  const receiveQtyDrafts = reactive<Record<number, string>>({})
  const bulkShipping = ref(false)
  const bulkReceiving = ref(false)

  const detailData = toRef(detailDataProp, 'value')

  const isStockinRecord = computed(() => detailData.value?.record_type === 'stockin')

  const totalProcesses = computed(() => processes.value.length)
  const completedProcesses = computed(() => processes.value.filter((p) => p.status === 'received').length)
  const detailProgress = computed(() => {
    const total = totalProcesses.value
    if (!total) return 0
    return Math.round((completedProcesses.value / total) * 100)
  })
  const detailStatusLabel = computed(() => {
    const total = totalProcesses.value
    if (!total) return '未配置工序'
    if (completedProcesses.value === total) return '外发完成'
    const started = processes.value.filter((p) => p.status !== 'pending').length
    const cur = processes.value.find((p) => p.status !== 'received')
    return started > 0 ? `进行中（${cur?.process_type || ''}）` : '待发货'
  })
  const detailStatusClass = computed(() => {
    if (detailProgress.value === 100) return 'completed'
    if (detailProgress.value > 0) return 'in_progress'
    return 'pending'
  })

  const processGroups = computed<ProcessGroup[]>(() => {
    const groups = new Map<string, ProcessGroup>()
    for (const p of processes.value) {
      const key = String(p.order_item_id ?? 'order')
      if (!groups.has(key)) {
        const sku = (detailData.value?.items || []).find((s) => s.id === p.order_item_id)
        groups.set(key, {
          itemId: p.order_item_id ?? null,
          skuName: sku?.product_name || p.product_name || 'SKU',
          skuQty: sku?.quantity || 0,
          processes: [],
        })
      }
      groups.get(key)!.processes.push(p)
    }
    if (groups.size === 0 && detailData.value) {
      const items = detailData.value.items || []
      if (items.length > 0) {
        for (const sku of items) {
          groups.set(String(sku.id), { itemId: sku.id, skuName: sku.product_name || 'SKU', skuQty: sku.quantity || 0, processes: [] })
        }
      } else {
        groups.set('order', { itemId: null, skuName: detailData.value.product_name || 'SKU', skuQty: detailData.value.quantity || 0, processes: [] })
      }
    }
    return Array.from(groups.values())
  })

  const processRows = computed(() => processes.value)

  /** 某道工序的目标数量（所属 SKU/订单数量） */
  function skuQtyOf(p: OrderOutsourceProcess): number {
    const group = processGroups.value.find((g) => g.processes.some((x) => x.id === p.id))
    return group?.skuQty || detailData.value?.quantity || 0
  }

  /** 某道工序剩余待发数量（目标 - 已发，下限 0） */
  function remainingShipQty(p: OrderOutsourceProcess): number {
    return Math.max(0, skuQtyOf(p) - (p.shipped_quantity || 0))
  }

  /** 某道工序剩余待收数量（已发 - 已收，下限 0） */
  function remainingReceiveQty(p: OrderOutsourceProcess): number {
    return Math.max(0, (p.shipped_quantity || 0) - (p.received_quantity || 0))
  }

  /** 可一键发货的工序数（有待发剩余即可：收货只闭环本批，不封锁后续批次） */
  const pendingCount = computed(
    () => processes.value.filter((p) => remainingShipQty(p) > 0).length,
  )
  /** 可一键收货的工序数（有待收剩余） */
  const shippedCount = computed(() => processes.value.filter((p) => remainingReceiveQty(p) > 0).length)

  // ==================== 台账（只读汇总） ====================

  /** 订单总数量（按 SKU 件数合计） */
  const totalQty = computed(() => processGroups.value.reduce((sum, g) => sum + (g.skuQty || 0), 0))
  /** 已发货合计（按工序累计：同一 SKU 的多道工序各自发货，分别计入） */
  const shippedTotal = computed(() => processes.value.reduce((sum, p) => sum + (p.shipped_quantity || 0), 0))
  /** 已收货合计（按工序累计） */
  const receivedTotal = computed(() => processes.value.reduce((sum, p) => sum + (p.received_quantity || 0), 0))
  /** 未发货合计（按工序累计剩余，与「未发货清单」口径一致）
   *  修复：此前用 totalQty - shippedTotal，把 SKU 件数与工序累计两种口径相减，
   *  同一 SKU 有多道工序时会系统性偏小，甚至首道工序发满后即显示为 0。 */
  const remainingTotal = computed(() => processes.value.reduce((sum, p) => sum + remainingShipQty(p), 0))
  /** 发货记录（流水，时间倒序） */
  const shipRecords = computed(() => flows.value.filter((f) => f.action === 'ship'))
  /** 收货记录（流水，时间倒序） */
  const receiveRecords = computed(() => flows.value.filter((f) => f.action === 'receive'))
  /** 未发货清单：工序 / 目标 / 已发 / 剩余 */
  const remainingList = computed(() =>
    processes.value
      .filter((p) => remainingShipQty(p) > 0)
      .map((p) => ({
        process_type: p.process_type,
        target: skuQtyOf(p),
        shipped: p.shipped_quantity || 0,
        remaining: remainingShipQty(p),
      })),
  )

  function progressVariant(progress: number): 'primary' | 'success' | 'warning' | 'danger' {
    if (progress === 100) return 'success'
    if (progress > 0) return 'warning'
    return 'warning'
  }

  async function loadProcesses(orderId: number) {
    loadingProcesses.value = true
    processes.value = []
    // 清空数量草稿，避免跨订单/重载后残留旧值
    for (const k of Object.keys(shipQtyDrafts)) delete shipQtyDrafts[Number(k)]
    for (const k of Object.keys(receiveQtyDrafts)) delete receiveQtyDrafts[Number(k)]
    try {
      const res = await outsourceApi.orderProcesses(orderId)
      processes.value = res.data ?? []
    } catch {
      toast.error('加载外发工序失败')
    } finally {
      loadingProcesses.value = false
    }
  }

  async function loadFlows(orderId: number) {
    try {
      const res = await outsourceApi.orderFlows(orderId)
      flows.value = res.data ?? []
    } catch {
      flows.value = []
    }
  }

  function reloadDetail() {
    if (detailData.value) {
      loadProcesses(detailData.value.id)
      loadFlows(detailData.value.id)
    }
    emit('refresh')
  }

  /** 写入某道工序的本批发货数量草稿（表格输入） */
  function setShipQty(id: number, value: string) {
    shipQtyDrafts[id] = value
  }

  /** 写入某道工序的本批收货数量草稿（表格输入） */
  function setReceiveQty(id: number, value: string) {
    receiveQtyDrafts[id] = value
  }

  /** 提取后端返回的错误文案（批量接口任一条失败会整批 400 并带上明细） */
  function errorDetail(e: unknown, fallback: string): string {
    return (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
  }

  /** 数量草稿解析结果：未填（默认剩余量）/ 无效（拒绝并提示）/ 有效正整数 */
  type ParsedQtyDraft = { kind: 'unfilled' } | { kind: 'invalid' } | { kind: 'qty'; qty: number }

  /**
   * 解析一键发货/收货的数量草稿（2026-10-19 审计 P1-21）。
   * 此前 `Number(draft) || remaining` 把显式输入的 0 / 清空一并当成「未填」
   * 静默回退为全部剩余量——实际发货量大于用户意图，且后端 gt=0 校验拦不住
   * 回退值（拦到的只有负数/非整数透传）。改为显式三分支：
   * 未填（undefined/空串/纯空白）→ 调用方取默认剩余量；
   * 0/负数/非整数 → 拒绝并提示；正整数 → 原样使用。
   */
  function parseQtyDraft(raw: string | undefined): ParsedQtyDraft {
    if (raw === undefined || raw.trim() === '') return { kind: 'unfilled' }
    const n = Number(raw)
    if (!Number.isInteger(n) || n < 1) return { kind: 'invalid' }
    return { kind: 'qty', qty: n }
  }

  /** 一键发货：所有有待发剩余的工序，单请求单事务批量发货（数量取各行输入，缺省剩余） */
  async function handleBulkShip() {
    const targets = processes.value.filter((p) => remainingShipQty(p) > 0)
    if (targets.length === 0) {
      toast.info('没有待发货的工序')
      return
    }
    const orderId = detailData.value?.id
    if (!orderId) return
    const items: { process_id: number; quantity: number }[] = []
    for (const p of targets) {
      const parsed = parseQtyDraft(shipQtyDrafts[p.id])
      if (parsed.kind === 'invalid') {
        toast.error(`工序「${p.process_type}」的数量输入无效（${shipQtyDrafts[p.id]}）：须为正整数，留空则默认全部剩余量`)
        return
      }
      items.push({ process_id: p.id, quantity: parsed.kind === 'unfilled' ? remainingShipQty(p) : parsed.qty })
    }
    bulkShipping.value = true
    try {
      await outsourceApi.shipProcessesBatch(orderId, items)
      for (const p of targets) delete shipQtyDrafts[p.id]
      toast.success(`全部 ${targets.length} 道工序已发货`)
    } catch (e) {
      toast.error(errorDetail(e, '一键发货失败（整批已回滚）'))
    } finally {
      bulkShipping.value = false
      reloadDetail()
    }
  }

  /** 一键收货：所有有待收剩余的工序，单请求单事务批量收货（数量取各行输入，缺省剩余） */
  async function handleBulkReceive() {
    const targets = processes.value.filter((p) => remainingReceiveQty(p) > 0)
    if (targets.length === 0) {
      toast.info('没有待收货的工序')
      return
    }
    const orderId = detailData.value?.id
    if (!orderId) return
    const items: { process_id: number; quantity: number }[] = []
    for (const p of targets) {
      const parsed = parseQtyDraft(receiveQtyDrafts[p.id])
      if (parsed.kind === 'invalid') {
        toast.error(`工序「${p.process_type}」的数量输入无效（${receiveQtyDrafts[p.id]}）：须为正整数，留空则默认全部剩余量`)
        return
      }
      items.push({ process_id: p.id, quantity: parsed.kind === 'unfilled' ? remainingReceiveQty(p) : parsed.qty })
    }
    bulkReceiving.value = true
    try {
      await outsourceApi.receiveProcessesBatch(orderId, items)
      for (const p of targets) delete receiveQtyDrafts[p.id]
      toast.success(`全部 ${targets.length} 道工序已确认收货`)
    } catch (e) {
      toast.error(errorDetail(e, '一键收货失败（整批已回滚）'))
    } finally {
      bulkReceiving.value = false
      reloadDetail()
    }
  }

  function statusLabel(status: string): string {
    return ({ pending: '待发货', shipped: '已发货', received: '已收货' } as Record<string, string>)[status] || status
  }

  return {
    canShip,
    canReceive,
    processes,
    loadingProcesses,
    flows,
    shipQtyDrafts,
    receiveQtyDrafts,
    bulkShipping,
    bulkReceiving,
    pendingCount,
    shippedCount,
    totalQty,
    shippedTotal,
    receivedTotal,
    remainingTotal,
    shipRecords,
    receiveRecords,
    remainingList,
    remainingShipQty,
    remainingReceiveQty,
    setShipQty,
    setReceiveQty,
    loadFlows,
    isStockinRecord,
    totalProcesses,
    completedProcesses,
    detailProgress,
    detailStatusLabel,
    detailStatusClass,
    processGroups,
    processRows,
    progressVariant,
    loadProcesses,
    handleBulkShip,
    handleBulkReceive,
    statusLabel,
  }
}
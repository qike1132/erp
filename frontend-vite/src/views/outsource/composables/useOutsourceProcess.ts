import { computed, reactive, ref, toRef, watch, type Ref } from 'vue'
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
  const canManage = computed(() => authStore.hasPermission('outsource_manage'))
  /** 贝乐用户：仅确认收货，不可发货 */
  const isBeile = computed(() => authStore.user?.username === '贝乐')
  /** 发货权限：非贝乐用户可发货 */
  const canShip = computed(() => canManage.value && !isBeile.value)
  /** 确认收货权限：仅贝乐用户 */
  const canReceive = computed(() => canManage.value && isBeile.value)

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

  /** 可一键发货的工序数（有待发剩余且未开始收货） */
  const pendingCount = computed(
    () => processes.value.filter((p) => remainingShipQty(p) > 0 && (p.received_quantity || 0) === 0).length,
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

  /** 一键发货：所有有待发剩余且未开始收货的工序按剩余发货（数量取各行输入，缺省剩余） */
  async function handleBulkShip() {
    const targets = processes.value.filter((p) => remainingShipQty(p) > 0 && (p.received_quantity || 0) === 0)
    if (targets.length === 0) {
      toast.info('没有待发货的工序')
      return
    }
    bulkShipping.value = true
    let ok = 0
    const errors: string[] = []
    for (const p of targets) {
      const qty = Number(shipQtyDrafts[p.id]) || remainingShipQty(p)
      try {
        await outsourceApi.shipProcess(p.id, qty)
        delete shipQtyDrafts[p.id]
        ok += 1
      } catch (e) {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        errors.push(`「${p.process_type}」${msg || '发货失败'}`)
      }
    }
    bulkShipping.value = false
    if (errors.length === 0) {
      toast.success(`全部 ${ok} 道工序已发货`)
    } else {
      toast.error(`${ok} 道发货成功，${errors.length} 道失败：${errors.join('；')}`)
    }
    reloadDetail()
  }

  /** 一键收货：所有有待收剩余的工序按剩余收货（数量取各行输入，缺省剩余） */
  async function handleBulkReceive() {
    const targets = processes.value.filter((p) => remainingReceiveQty(p) > 0)
    if (targets.length === 0) {
      toast.info('没有待收货的工序')
      return
    }
    bulkReceiving.value = true
    let ok = 0
    const errors: string[] = []
    for (const p of targets) {
      const qty = receiveQtyDrafts[p.id] ? Number(receiveQtyDrafts[p.id]) : remainingReceiveQty(p)
      try {
        await outsourceApi.receiveProcess(p.id, qty)
        delete receiveQtyDrafts[p.id]
        ok += 1
      } catch (e) {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        errors.push(`「${p.process_type}」${msg || '确认收货失败'}`)
      }
    }
    bulkReceiving.value = false
    if (errors.length === 0) {
      toast.success(`全部 ${ok} 道工序已确认收货`)
    } else {
      toast.error(`${ok} 道收货成功，${errors.length} 道失败：${errors.join('；')}`)
    }
    reloadDetail()
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
import { computed, ref, toRef, watch, type Ref } from 'vue'
import { outsourceApi } from '@/api/outsource'
import type { OrderOutsourceProcess } from '@/api/outsource'
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

  const processes = ref<OrderOutsourceProcess[]>([])
  const loadingProcesses = ref(false)
  const generating = ref(false)

  const detailData = toRef(detailDataProp, 'value')

  const isStockinRecord = computed(() => detailData.value?.record_type === 'stockin')

  const detailTotalQuantity = computed(() => {
    if (!detailData.value) return 0
    const items = detailData.value.items || []
    if (items.length === 0) return detailData.value.quantity || 0
    return items.reduce((sum, s) => sum + (s.quantity || 0), 0)
  })

  const totalProcesses = computed(() => processes.value.length)
  const completedProcesses = computed(() => processes.value.filter((p) => p.status === 'completed').length)
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
    const cur = processes.value.find((p) => p.status !== 'completed')
    return started > 0 ? `进行中（${cur?.process_type || ''}）` : '待开始'
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

  function progressVariant(progress: number): 'primary' | 'success' | 'warning' | 'danger' {
    if (progress === 100) return 'success'
    if (progress > 0) return 'warning'
    return 'primary'
  }

  async function loadProcesses(orderId: number) {
    loadingProcesses.value = true
    processes.value = []
    try {
      const res = await outsourceApi.orderProcesses(orderId)
      processes.value = res.data ?? []
    } catch {
      toast.error('加载外发工序失败')
    } finally {
      loadingProcesses.value = false
    }
  }

  function reloadDetail() {
    if (detailData.value) loadProcesses(detailData.value.id)
    emit('refresh')
  }

  async function handleGenerate() {
    if (!detailData.value) return
    generating.value = true
    try {
      const res = await outsourceApi.generateProcesses(detailData.value.id)
      toast.success(res.message || '工序已生成')
      await loadProcesses(detailData.value.id)
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || '生成工序失败')
    } finally {
      generating.value = false
    }
  }

  async function handleStart(p: OrderOutsourceProcess) {
    try {
      if (p.status === 'in_progress') {
        await outsourceApi.completeProcess(p.id)
        toast.success(`「${p.process_type}」已完成`)
      } else {
        await outsourceApi.startProcess(p.id)
        toast.success(`「${p.process_type}」已开始`)
      }
      reloadDetail()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || '操作失败')
    }
  }

  async function handleCompleteDirect(p: OrderOutsourceProcess) {
    try {
      await outsourceApi.completeProcess(p.id)
      toast.success(`「${p.process_type}」已完成`)
      reloadDetail()
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || '操作失败')
    }
  }

  async function handleDeleteProcess(p: OrderOutsourceProcess) {
    try {
      await outsourceApi.deleteProcess(p.id)
      toast.success(`已删除工序「${p.process_type}」`)
      reloadDetail()
    } catch {
      toast.error('删除失败')
    }
  }

  async function updatePlanned(p: OrderOutsourceProcess, field: 'planned_start_time' | 'planned_end_time', value: string) {
    try {
      const iso = value ? new Date(value).toISOString() : null
      await outsourceApi.updateProcess(p.id, { [field]: iso })
      toast.success('计划时间已更新')
      if (detailData.value) await loadProcesses(detailData.value.id)
    } catch {
      toast.error('更新失败')
    }
  }

  function toDateTimeLocal(v?: string | null): string {
    if (!v) return ''
    const [datePart, timePart] = v.split(' ')
    if (!timePart) return datePart || ''
    return `${datePart}T${timePart}`
  }

  function statusLabel(status: string): string {
    return ({ pending: '待开始', in_progress: '进行中', completed: '已完成' } as Record<string, string>)[status] || status
  }

  function shortDate(v?: string | null): string {
    if (!v) return '-'
    return v.length > 16 ? v.slice(0, 16) : v
  }

  return {
    canManage,
    processes,
    loadingProcesses,
    generating,
    isStockinRecord,
    detailTotalQuantity,
    totalProcesses,
    completedProcesses,
    detailProgress,
    detailStatusLabel,
    detailStatusClass,
    processGroups,
    processRows,
    progressVariant,
    loadProcesses,
    handleGenerate,
    handleStart,
    handleCompleteDirect,
    handleDeleteProcess,
    updatePlanned,
    toDateTimeLocal,
    statusLabel,
    shortDate,
  }
}
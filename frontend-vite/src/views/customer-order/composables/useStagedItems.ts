/**
 * useStagedItems — 暂存项动作域（批次 2-3 拆分自 useOrderActions）
 *
 * 承载暂存订单/备货条目状态、删除与批量提交（含部分失败保留重试语义）。
 * 函数逻辑自 useOrderActions.ts 原样搬移。
 */
import { ref, computed, type Ref, type ComputedRef } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { stockApi, type BatchSubmitResponse } from '@/api'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import { invalidateOrderDerivedQueries } from '@/utils/queryKeys'
import type { StagedItem } from './types'

/** 兼容旧名，实际类型来自 API 层（避免两处定义漂移） */
export type BatchSubmitOrdersResponse = BatchSubmitResponse

/**
 * 单类条目（订单 / 备货）的提交结果。
 *
 * 关键不变量：`failed` 只在**真的发出过请求并失败**时为 true；
 * 未尝试（`attempted === false`）既不等于成功、也不等于失败。
 * 移除条目与播报文案都由此结构派生，二者因此不可能互相矛盾。
 */
export interface SubmitOutcome {
  attempted: boolean
  failed: boolean
  /** 该类本次涉及的条目数（未尝试时为 0） */
  count: number
  res: BatchSubmitOrdersResponse | null
}

/** 唯一标识生成已上移为共享实现（components/ocr 粘贴识别同用） */
export { genUid } from '@/utils/uid'

export function useStagedItems() {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()

  const stagedItems = ref<StagedItem[]>([])

  async function removeStagedItem(uid: string) {
    const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
    if (!ok) return
    // 通过 uid 安全定位，避免异步 confirm 期间索引失效
    const idx = stagedItems.value.findIndex((i) => i.uid === uid)
    if (idx >= 0) stagedItems.value.splice(idx, 1)
  }

  const stagedOrders = computed(() => stagedItems.value.filter((i) => i.type === 'order'))
  const stagedStockins = computed(() => stagedItems.value.filter((i) => i.type === 'stockin'))

  const submitting = ref(false)

  /**
   * 提交一类条目。成功/失败只记录事实并提示错误，不抛出，
   * 交由 submitAll 统一决策「移除什么、播报什么」。
   */
  async function submitGroup(
    submit: (payload: Record<string, unknown>[]) => Promise<BatchSubmitOrdersResponse>,
    payload: Record<string, unknown>[],
    label: string,
  ): Promise<SubmitOutcome> {
    if (!payload.length) return { attempted: false, failed: false, count: 0, res: null }
    try {
      const res = await submit(payload)
      return { attempted: true, failed: false, count: payload.length, res }
    } catch (e: unknown) {
      showToast(getErrorMessage(e, `${label}提交失败`), 'error')
      return { attempted: true, failed: true, count: payload.length, res: null }
    }
  }

  function buildOrderPayload() {
    return stagedOrders.value.map((i) => ({
      product_id: i.productId,
      customer: i.customer,
      quantity: i.quantity,
      deduct_stock: i.deductStock || false,
      deduct_quantity: i.deductQuantity || 0,
      note: i.note || '',
      order_date: i.date || '',
      // 分批出货计划（2026-10-06 v2）：空数组 = 无计划；各批总和已在前端排满校验
      shipment_plans: i.shipmentPlans.map((s) => ({ plan_date: s.date, quantity: s.quantity, note: s.note || '' })),
    }))
  }

  function buildStockinPayload() {
    return stagedStockins.value.map((i) => ({
      product_id: i.productId,
      customer: i.customer,
      quantity: i.quantity,
      note: i.note || '',
      stockin_date: i.date || '',
    }))
  }

  /** 只移除已确认提交成功的条目，失败与未尝试的一律保留供重试 */
  function dropUids(uids: string[]) {
    if (!uids.length) return
    stagedItems.value = stagedItems.value.filter((i) => !uids.includes(i.uid))
  }

  /**
   * 备货提交的逐条结果。后端 `batch_create_stockins` 用 `results[idx]` 按下标构造
   * （stock_in_service.py:193/205/207/210），与提交的 payload 一一对应；
   * 形状不符（缺 results 或长度不等）时返回 null，调用方退回「整批视为成功」的旧行为，
   * 避免误判把已入库的行留在暂存区被重复提交。
   */
  function stockinOutcome(payload: Record<string, unknown>[], res: BatchSubmitOrdersResponse | null) {
    const body = (res as { data?: BatchSubmitOrdersResponse } | null)?.data ?? res
    const results = (body as { results?: { success?: boolean }[] } | null)?.results
    if (!Array.isArray(results) || results.length !== payload.length) return null
    const okFlags = results.map((r) => r?.success === true)
    return {
      okFlags,
      okCount: okFlags.filter(Boolean).length,
      okQty: payload.reduce((sum, item, i) => sum + (okFlags[i] ? Number(item.quantity) || 0 : 0), 0),
    }
  }

  /**
   * 统一播报。所有措辞都由 order/stockin 两个真实结果派生，
   * 因此不会出现「播报成功但实际未提交」这类与事实相反的反馈。
   * syncedPlanCount：本次成功提交且带出货计划的订单条目数（在移除暂存项之前捕获）。
   * stockinOkQty/stockinOkCount：备货**逐条成功**的件数与条数；stockinFailedCount：未入库条数。
   * 备货直接增加库存，成功文案必须报出条数与件数——只报订单会让备货入库在用户眼前消失，
   * 库存"凭空"多出（2026-10-06 MINISO 出库事故的根因之一）。
   */
  function reportSubmit(
    order: SubmitOutcome,
    stockin: SubmitOutcome,
    syncedPlanCount = 0,
    stockinOkQty = 0,
    stockinOkCount = 0,
    stockinFailedCount = 0,
  ) {
    const done: string[] = []
    const kept: string[] = []
    if (order.attempted && !order.failed) done.push(`订单 ${order.count} 条`)
    if (stockin.attempted && !stockin.failed) {
      // HTTP 200 只代表请求成功，逐条结果才算数：部分失败不能按整批报
      if (stockinOkCount > 0) {
        const failedNote = stockinFailedCount > 0 ? `，${stockinFailedCount} 条未入库（已保留可重试）` : ''
        done.push(`备货入库 ${stockinOkCount} 条（库存 +${stockinOkQty}）${failedNote}`)
      } else if (stockinFailedCount > 0) {
        kept.push(`备货 ${stockinFailedCount} 条`)
      }
    }
    if (order.attempted && order.failed) kept.push(`订单 ${order.count} 条`)
    if (stockin.attempted && stockin.failed) kept.push(`备货 ${stockin.count} 条`)

    if (kept.length) {
      const head = done.length ? `已提交：${done.join('、')}；` : ''
      showToast(`${head}提交失败：${kept.join('、')}（已保留，可重新提交）`, done.length ? 'warning' : 'error')
      return
    }
    if (!order.attempted) {
      // 走到这里说明本次只提交了备货（done 仅含备货段）
      showToast(`提交成功：${done.join('、')}`, 'success')
      return
    }
    const res = order.res?.data ?? order.res
    const createdCount = res?.created_count ?? 0
    if (createdCount === 0) {
      const firstError = (res?.results ?? []).filter((r) => !r.success)[0]?.error || '未知原因'
      const stockinNote = done.find((s) => s.startsWith('备货'))
      showToast(`订单创建失败（0/${order.count}）：${firstError}${stockinNote ? `；${stockinNote}` : ''}`, 'error')
      return
    }
    const stockinNote = done.find((s) => s.startsWith('备货'))
    const stockinTail = stockinNote ? `；${stockinNote}` : ''
    if (syncedPlanCount > 0) {
      showToast(`提交成功：已创建 ${createdCount} 个主订单（含 ${order.count} 个 SKU），其中 ${syncedPlanCount} 条已同步出货计划${stockinTail}`, 'success')
      return
    }
    showToast(`提交成功：已创建 ${createdCount} 个主订单（含 ${order.count} 个 SKU）${stockinTail}`, 'success')
  }

  async function submitAll() {
    if (!stagedItems.value.length || submitting.value) return
    submitting.value = true
    try {
      const orderUids = stagedOrders.value.map((i) => i.uid)
      const stockinUids = stagedStockins.value.map((i) => i.uid)
      // 提交内容在 await 之前定稿。提交在途期间用户仍可改暂存区（表单未接 submitting），
      // 播报必须以「实际提交的那一批」为准——事后从活列表现算会与实际入库对不上。
      const orderPayload = buildOrderPayload()
      const stockinPayload = buildStockinPayload()
      // 「带计划」计数与 payload 同点定稿：submitGroup 的两个 await 期间
      // removeStagedItem 可能让暂存区变短，事后过滤会漏算
      const orderWithPlans = stagedOrders.value.filter((i) => i.shipmentPlans.length > 0).length

      // 两类条目各自独立提交：其一失败不阻断另一类，
      // 也不会把「从未尝试」错当成「已成功」（后者曾导致条目被静默移出暂存区）。
      const order = await submitGroup(stockApi.batchSubmitOrders, orderPayload, '订单')
      const stockin = await submitGroup(stockApi.batchSubmitStockins, stockinPayload, '备货')

      // 在移除暂存项之前捕获「成功提交且带计划」的条目数（await 前已定稿），供播报使用
      const syncedPlanCount = order.attempted && !order.failed ? orderWithPlans : 0
      // 备货按**逐条结果**统计：请求返回 200 不代表每条都入库成功
      const stockinRes = stockin.attempted && !stockin.failed
        ? stockinOutcome(stockinPayload, stockin.res)
        : null
      const stockinOkCount = stockinRes ? stockinRes.okCount : stockin.count
      const stockinOkQty = stockinRes
        ? stockinRes.okQty
        : stockinPayload.reduce((sum, i) => sum + (Number(i.quantity) || 0), 0)
      const stockinFailedCount = stockinRes ? stockin.count - stockinRes.okCount : 0

      // 移除与播报共用同一组事实，二者不可能不一致
      if (order.attempted && !order.failed) dropUids(orderUids)
      if (stockin.attempted && !stockin.failed) {
        // 只移除**真正入库成功**的那几条；逐条失败的行留在暂存区供重试
        // （形状不符时 stockinRes 为 null，退回整批移除，避免重复入库）
        dropUids(stockinRes ? stockinUids.filter((_, i) => stockinRes.okFlags[i]) : stockinUids)
      }

      reportSubmit(order, stockin, syncedPlanCount, stockinOkQty, stockinOkCount, stockinFailedCount)

      // 订单 / 备货任一写入成功都会改变库存汇总与报表流水，统一失效派生查询
      const orderSubmitted = order.attempted && !order.failed
      const stockinSubmitted = stockin.attempted && !stockin.failed
      if (orderSubmitted || stockinSubmitted) invalidateOrderDerivedQueries(queryClient)
    } finally {
      submitting.value = false
    }
  }

  return {
    stagedItems: stagedItems as Ref<StagedItem[]>,
    stagedOrders: stagedOrders as ComputedRef<StagedItem[]>,
    stagedStockins: stagedStockins as ComputedRef<StagedItem[]>,
    submitting,
    removeStagedItem,
    submitAll,
    confirmDialog,
  }
}

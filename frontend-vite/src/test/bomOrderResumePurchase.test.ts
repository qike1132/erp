import { beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, reactive, ref } from 'vue'
import { useBomOrderResume } from '@/views/purchase/composables/useBomOrderResume'
import {
  createResumeAttempt, readResumeAttempt, writeResumeAttempt,
  type BomResumeAttemptV1, type PurchaseViewSnapshot,
} from '@/utils/bomOrderResume'

const ATTEMPT_ID = '22222222-2222-4222-8222-222222222222'
const snapshot: PurchaseViewSnapshot = {
  active_tab: 'active', purchase_page: 2, unprocessed_page: 1,
  selected_ids: [11, 99], main_scroll_top: 0, table_scroll_left: 0,
}

function attempt(phase: BomResumeAttemptV1['phase'] = 'RETURNING') {
  const value = createResumeAttempt({
    attempt_id: ATTEMPT_ID,
    owner_id: 7,
    source: { composite_id: 'order:42', record_type: 'order', source_order_id: 42, order_no: 'SO-42' },
    pending_products: [{ product_id: 5, product_name: '产品五' }],
    current_product_id: 5,
    view: snapshot,
    now: Date.now(),
  })
  value.phase = phase
  return value
}

function row(hasBom: boolean) {
  return {
    id: 42, composite_id: 'order:42', record_type: 'order' as const,
    source_order_id: 42, order_no: 'SO-42', customer: '客户', product_id: 5,
    product_name: '产品五', quantity: 2, order_date: '', status: '待备货', has_bom: hasBom,
    items: [{ id: 1, product_id: 5, product_name: '产品五', quantity: 2, has_bom: hasBom }],
  }
}

function harness(options: {
  phase?: BomResumeAttemptV1['phase']
  hasBom?: boolean
  hasPermission?: boolean
  withContext?: boolean
} = {}) {
  const generate = vi.fn().mockResolvedValue({
    success: true, code: 'OK', created_count: 1, idempotent: false,
    orders: [{ id: 88, order_no: 'PO-88' }],
  })
  const push = vi.fn().mockResolvedValue(undefined)
  const replace = vi.fn().mockResolvedValue(undefined)
  const unprocessed = reactive({
    orders: [row(options.hasBom ?? true)], currentPage: 1, totalPages: 1,
    refresh: vi.fn().mockResolvedValue(undefined), load: vi.fn(),
  })
  const purchaseOrders = reactive({
    orders: [{
      id: 11, order_no: 'PO-11', status: 'pending', customer_name: '客户',
      supplier_name: '供应商', create_time: '', order_date: '',
    }],
    page: 1, selectedIds: [11, 99],
    refresh: vi.fn().mockResolvedValue(undefined), load: vi.fn(),
  })
  if (options.withContext !== false) writeResumeAttempt(attempt(options.phase))
  const scope = effectScope()
  const resume = scope.run(() => useBomOrderResume({
    activeTab: ref<'active' | 'history'>('history'),
    unprocessed,
    purchaseOrders,
    route: { query: { resume: ATTEMPT_ID } },
    router: { push, replace },
    auth: {
      user: { id: 7 },
      hasPermission: vi.fn().mockReturnValue(options.hasPermission ?? true),
    },
    generate,
  }))!
  return { resume, generate, push, replace, unprocessed, purchaseOrders, scope }
}

describe('采购缺 BOM 入口', () => {
  beforeEach(() => sessionStorage.clear())

  it('无 product_manage 不创建上下文也不跳转', async () => {
    const h = harness({ hasPermission: false, withContext: false })
    await h.resume.startConfiguration(row(false) as never)
    expect(h.push).not.toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
    h.scope.stop()
  })

  it('保存 typed 来源与视图后只跳首个缺 BOM 产品', async () => {
    const h = harness({ withContext: false })
    await h.resume.startConfiguration(row(false) as never)
    expect(h.push).toHaveBeenCalledWith({
      path: '/product',
      query: { product_id: '5', resume_attempt_id: expect.any(String) },
    })
    const query = h.push.mock.calls[0]![0].query
    const saved = readResumeAttempt(query.resume_attempt_id, 7)
    expect(saved?.source.composite_id).toBe('order:42')
    expect(saved?.view.purchase_page).toBe(1)
    h.scope.stop()
  })

  it('入口并发重复点击只创建一次上下文与导航', async () => {
    const h = harness({ withContext: false })
    const first = h.resume.startConfiguration(row(false) as never)
    const second = h.resume.startConfiguration(row(false) as never)
    await Promise.all([first, second])
    expect(h.push).toHaveBeenCalledTimes(1)
    expect(sessionStorage.length).toBe(1)
    h.scope.stop()
  })
})

describe('采购返回：先恢复并强制刷新，再决定是否写', () => {
  beforeEach(() => sessionStorage.clear())

  it('刷新 Promise 未完成前不得续提；完成后同 attempt/key 调用一次', async () => {
    const h = harness()
    let release!: () => void
    const pendingRefresh = new Promise<void>((resolve) => { release = resolve })
    h.unprocessed.refresh.mockImplementation(() => pendingRefresh)
    const initializing = h.resume.initializeFromRoute()
    await vi.waitFor(() => expect(h.unprocessed.refresh).toHaveBeenCalled())
    expect(h.generate).not.toHaveBeenCalled()
    release()
    await initializing
    expect(h.unprocessed.refresh).toHaveBeenCalledTimes(2)
    expect(h.purchaseOrders.refresh).toHaveBeenCalledTimes(2)
    expect(h.generate).toHaveBeenCalledTimes(1)
    expect(h.unprocessed.refresh.mock.invocationCallOrder[0])
      .toBeLessThan(h.generate.mock.invocationCallOrder[0]!)
    expect(h.generate).toHaveBeenCalledWith(
      { composite_ids: ['order:42'] },
      { headers: { 'X-Idempotency-Key': `po-resume:${ATTEMPT_ID}` } },
    )
    expect(h.purchaseOrders.selectedIds).toEqual([11])
    expect(readResumeAttempt(ATTEMPT_ID, 7)).toBeNull()
    h.scope.stop()
  })

  it('仍缺 BOM 为 WAITING_NEXT_BOM 且 0 写，不自动连跳', async () => {
    const h = harness({ hasBom: false })
    await h.resume.initializeFromRoute()
    expect(h.generate).not.toHaveBeenCalled()
    expect(h.push).not.toHaveBeenCalled()
    expect(h.resume.phase.value).toBe('WAITING_NEXT_BOM')
    expect(h.resume.pendingProducts.value.map((p) => p.product_id)).toEqual([5])
    h.scope.stop()
  })

  it('网络未知后手动重试仍先刷新并复用同 key', async () => {
    const h = harness()
    h.generate.mockRejectedValueOnce(new Error('network'))
    await h.resume.initializeFromRoute()
    expect(h.resume.phase.value).toBe('RESUME_FAILED')
    const firstKey = h.generate.mock.calls[0]![1].headers['X-Idempotency-Key']
    await h.resume.retryResume()
    expect(h.generate).toHaveBeenCalledTimes(2)
    expect(h.generate.mock.calls[1]![1].headers['X-Idempotency-Key']).toBe(firstKey)
    // 两次进入均先刷新；第二次续提成功后刷新派生列表，故为 3 次。
    expect(h.unprocessed.refresh).toHaveBeenCalledTimes(3)
    expect(h.unprocessed.refresh.mock.invocationCallOrder[0])
      .toBeLessThan(h.generate.mock.invocationCallOrder[0]!)
    expect(h.unprocessed.refresh.mock.invocationCallOrder[1])
      .toBeLessThan(h.generate.mock.invocationCallOrder[1]!)
    h.scope.stop()
  })

  it('CANCELLED 只恢复并刷新，0 写；已消费旧 URL 也 0 写', async () => {
    const h = harness({ phase: 'CANCELLED' })
    await h.resume.initializeFromRoute()
    expect(h.generate).not.toHaveBeenCalled()
    expect(readResumeAttempt(ATTEMPT_ID, 7)).toBeNull()
    await h.resume.initializeFromRoute()
    expect(h.generate).not.toHaveBeenCalled()
    h.scope.stop()
  })
})

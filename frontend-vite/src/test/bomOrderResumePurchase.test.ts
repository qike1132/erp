import { beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, reactive, ref } from 'vue'
import { useBomOrderResume } from '@/views/purchase/composables/useBomOrderResume'
import {
  createResumeAttempt, readResumeAttempt, writeResumeAttempt,
  type BomResumeAttemptV1, type PurchaseViewSnapshot, type ResumeProduct,
} from '@/utils/bomOrderResume'

const ATTEMPT_ID = '22222222-2222-4222-8222-222222222222'
const snapshot: PurchaseViewSnapshot = {
  active_tab: 'active', purchase_page: 2, unprocessed_page: 1,
  selected_ids: [11, 99], main_scroll_top: 0, table_scroll_left: 0,
}

const PRODUCT_FIVE: ResumeProduct = { product_id: 5, product_name: '产品五', product_barcode: null }
const PRODUCT_SIX: ResumeProduct = { product_id: 6, product_name: '产品六', product_barcode: null }

function attempt(
  phase: BomResumeAttemptV1['phase'] = 'RETURNING',
  pendingProducts: ResumeProduct[] = [PRODUCT_FIVE],
) {
  const value = createResumeAttempt({
    attempt_id: ATTEMPT_ID,
    owner_id: 7,
    source: { composite_id: 'order:42', record_type: 'order', source_order_id: 42, order_no: 'SO-42' },
    pending_products: pendingProducts,
    current_product_id: pendingProducts[0]?.product_id ?? 5,
    view: snapshot,
    now: Date.now(),
  })
  value.phase = phase
  return value
}

function row(hasBom: boolean, extraItems: Array<{
  id: number; product_id: number; product_name: string; quantity: number; has_bom: boolean
}> = []) {
  return {
    id: 42, composite_id: 'order:42', record_type: 'order' as const,
    source_order_id: 42, order_no: 'SO-42', customer: '客户', product_id: 5,
    product_name: '产品五', quantity: 2, order_date: '', status: '待备货', has_bom: hasBom,
    items: [
      { id: 1, product_id: 5, product_name: '产品五', quantity: 2, has_bom: hasBom },
      ...extraItems,
    ],
  }
}

function harness(options: {
  phase?: BomResumeAttemptV1['phase']
  hasBom?: boolean
  hasPermission?: boolean
  withContext?: boolean
  pendingProducts?: ResumeProduct[]
  openBomEditor?: (product: ResumeProduct) => Promise<void> | void
} = {}) {
  const generate = vi.fn().mockResolvedValue({
    success: true, code: 'OK', created_count: 1, idempotent: false,
    orders: [{ id: 88, order_no: 'PO-88' }], missing_bom: [],
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
  if (options.withContext !== false) {
    writeResumeAttempt(attempt(options.phase, options.pendingProducts))
  }
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
    openBomEditor: options.openBomEditor,
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

  it('采购页配置 BOM 直接打开同页弹窗，不跳 /product', async () => {
    const openBomEditor = vi.fn().mockResolvedValue(undefined)
    const h = harness({ withContext: false, openBomEditor })
    await h.resume.startConfiguration(row(false) as never)
    expect(openBomEditor).toHaveBeenCalledTimes(1)
    expect(openBomEditor).toHaveBeenCalledWith(expect.objectContaining({
      product_id: 5, product_name: '产品五',
    }))
    expect(h.push).not.toHaveBeenCalled()
    h.scope.stop()
  })

  it('同页弹窗保存后刷新并按权威 MISSING_BOM 切到下一个 SKU，不跳 /product', async () => {
    const h = harness({ withContext: false, openBomEditor: vi.fn() })
    const twoMissing = row(false, [{
      id: 2, product_id: 6, product_name: '产品六', quantity: 3, has_bom: false,
    }])
    await h.resume.startConfiguration(twoMissing as never)
    h.generate.mockResolvedValue({
      success: false, code: 'MISSING_BOM', created_count: 0, idempotent: false,
      orders: [], missing_bom: [PRODUCT_SIX],
    })
    await h.resume.completeConfiguration(5)
    expect(h.resume.phase.value).toBe('WAITING_NEXT_BOM')
    expect(h.resume.pendingProducts.value).toEqual([PRODUCT_SIX])
    expect(h.push).not.toHaveBeenCalled()
    h.scope.stop()
  })

  it('同页弹窗保存后齐备时直接生成并结束，不跳 /product', async () => {
    const h = harness({ withContext: false, openBomEditor: vi.fn() })
    await h.resume.startConfiguration(row(false) as never)
    h.generate.mockResolvedValue({
      success: true, code: 'OK', created_count: 1, idempotent: false,
      orders: [{ id: 88, order_no: 'PO-88' }], missing_bom: [],
    })
    await h.resume.completeConfiguration(5)
    expect(h.resume.phase.value).toBe('DONE')
    expect(h.resume.message.value).toContain('PO-88')
    expect(h.push).not.toHaveBeenCalled()
    h.scope.stop()
  })

  it('同页弹窗取消只结束尝试，不生成采购单', async () => {
    const h = harness({ withContext: false, openBomEditor: vi.fn() })
    await h.resume.startConfiguration(row(false) as never)
    h.resume.cancelConfiguration()
    expect(h.resume.phase.value).toBe('CANCELLED')
    expect(readResumeAttempt(ATTEMPT_ID, 7)).toBeNull()
    expect(h.generate).not.toHaveBeenCalled()
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
    h.generate.mockResolvedValue({
      success: false, code: 'MISSING_BOM', created_count: 0, idempotent: false,
      orders: [], missing_bom: [PRODUCT_FIVE],
    })
    await h.resume.initializeFromRoute()
    // 列表快照仍缺 BOM 时也要调用权威端点：它会返回精确 missing_bom 且 0 写入。
    expect(h.generate).toHaveBeenCalledTimes(1)
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

  it('已有采购单/同键重放显示无需重复下单，不伪造新增', async () => {
    const h = harness()
    h.generate.mockResolvedValue({
      success: true, code: 'OK', created_count: 0, idempotent: true,
      orders: [{ id: 88, order_no: 'PO-88' }], missing_bom: [],
    })
    await h.resume.initializeFromRoute()
    expect(h.resume.phase.value).toBe('DONE')
    expect(h.resume.message.value).toContain('无需重复下单')
    expect(readResumeAttempt(ATTEMPT_ID, 7)).toBeNull()
    h.scope.stop()
  })

  it('后端返回 MISSING_BOM 时更新缺失 SKU，不自动连跳', async () => {
    const h = harness()
    h.generate.mockResolvedValue({
      success: false, code: 'MISSING_BOM', created_count: 0, idempotent: false,
      orders: [], missing_bom: [{ product_id: 6, product_name: '产品六' }],
    })
    await h.resume.initializeFromRoute()
    expect(h.resume.phase.value).toBe('WAITING_NEXT_BOM')
    expect(h.resume.pendingProducts.value).toEqual([{ product_id: 6, product_name: '产品六' }])
    expect(h.push).not.toHaveBeenCalled()
    h.scope.stop()
  })

  it('后端返回 SOURCE_INVALID 时中止并消费上下文', async () => {
    const h = harness()
    h.generate.mockResolvedValue({
      success: false, code: 'SOURCE_INVALID', message: '来源已删除',
      created_count: 0, idempotent: false, orders: [], missing_bom: [],
    })
    await h.resume.initializeFromRoute()
    expect(h.resume.phase.value).toBe('ABORTED')
    expect(h.resume.message.value).toContain('来源已删除')
    expect(readResumeAttempt(ATTEMPT_ID, 7)).toBeNull()
    h.scope.stop()
  })

  it('409 的结构化 detail 显示可读 message，而不是 [object Object]', async () => {
    const h = harness()
    h.generate.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: { code: 'IDEMPOTENCY_CONFLICT', message: '同键不同来源' } },
      },
    })
    await h.resume.initializeFromRoute()
    expect(h.resume.phase.value).toBe('ABORTED')
    expect(h.resume.message.value).toContain('同键不同来源')
    expect(h.resume.message.value).not.toContain('[object Object]')
    h.scope.stop()
  })

  it('成功但 0 单且非幂等时判为不可信响应，保留同键可人工重试', async () => {
    const h = harness()
    h.generate.mockResolvedValue({
      success: true, code: 'OK', created_count: 0, idempotent: false,
      orders: [{ id: 88, order_no: 'PO-88' }], missing_bom: [],
    })
    await h.resume.initializeFromRoute()
    expect(h.resume.phase.value).toBe('RESUME_FAILED')
    expect(readResumeAttempt(ATTEMPT_ID, 7)?.phase).toBe('RESUME_FAILED')
    h.scope.stop()
  })

  it('来源行已消失时仍按同来源续提，不把消失当成功或跳过', async () => {
    const h = harness()
    h.unprocessed.orders = []
    await h.resume.initializeFromRoute()
    expect(h.generate).toHaveBeenCalledTimes(1)
    expect(h.resume.phase.value).toBe('DONE')
    h.scope.stop()
  })

  it('列表快照仍把首个 SKU 标为缺 BOM 时，下一份必须用服务端权威列表，不能回跳第一个', async () => {
    const h = harness({ pendingProducts: [PRODUCT_FIVE, PRODUCT_SIX] })
    h.generate.mockResolvedValue({
      success: false, code: 'MISSING_BOM', created_count: 0, idempotent: false,
      orders: [], missing_bom: [PRODUCT_SIX],
    })
    const staleRow = {
      ...row(false),
      items: [
        { id: 1, product_id: 5, product_name: '产品五', quantity: 2, has_bom: false },
        { id: 2, product_id: 6, product_name: '产品六', quantity: 3, has_bom: false },
      ],
    }
    h.unprocessed.orders = [staleRow as never]

    await h.resume.initializeFromRoute()
    expect(h.resume.phase.value).toBe('WAITING_NEXT_BOM')
    expect(h.resume.pendingProducts.value).toEqual([PRODUCT_SIX])

    await h.resume.startConfiguration(staleRow as never)
    expect(h.push).toHaveBeenCalledWith({
      path: '/product',
      query: { product_id: '6', resume_attempt_id: expect.any(String) },
    })
    const saved = readResumeAttempt(ATTEMPT_ID, 7)
    expect(saved?.current_product_id).toBe(6)
    expect(saved?.pending_products).toEqual([PRODUCT_SIX])
    h.scope.stop()
  })
})

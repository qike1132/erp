/**
 * 订单页「粘贴图片识别 → 人工确认 → 进暂存区」行为测试。
 *
 * 识别与闸门在共享的 useOcrPaste（components/ocr，客户订单/出货两页共用），
 * 这里按 OrderInputPanel 的真实组合方式（buildStaged = buildOrderStagedItems）
 * 锁死四件事：
 *   1) customer 参数必须真的拼进 URL（本仓库 API 层踩过「参数被静默丢弃」的坑）
 *   2) 未匹配的产品不允许导入（没有 product_id 的话提交必然失败）
 *   3) 识别 0 条时进指引态而不是空表
 *   4) 确认后映射成 origin=ocr 的订单暂存条目，客户与日期取表单值
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mocks = vi.hoisted(() => ({
  uploadMock: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  upload: mocks.uploadMock,
  download: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import { showToast } from '@/composables/useToast'
import { useOcrPaste } from '@/components/ocr/useOcrPaste'
import { buildOrderStagedItems } from '@/views/customer-order/composables/useOrderOcrStaging'
import type { StagedItem } from '@/views/customer-order/composables/types'

const okItems = [
  {
    raw_product_name: '儿童保温杯500ml',
    product_id: 7,
    product_name: '儿童保温杯 500ml',
    match_confidence: 1,
    quantity: 50,
    unit: '箱',
    customer: '华东商贸',
    customer_id: 3,
    customer_confidence: 1,
    note: '',
  },
  {
    raw_product_name: '卡通雨伞8骨',
    product_id: null,
    product_name: '卡通雨伞8骨',
    match_confidence: 0,
    quantity: 30,
    unit: '把',
    customer: '',
    customer_id: null,
    customer_confidence: 0,
    note: '',
  },
]

function setup(collected: StagedItem[] = []) {
  const ocr = useOcrPaste({
    buildStaged: (drafts, ctx) => {
      collected.push(...buildOrderStagedItems(drafts, ctx))
      return true
    },
    getDefaultCustomer: () => '表单客户',
    getDefaultDate: () => '2026-09-29',
  })
  return { ocr, collected }
}

const file = (name = 'shot.png', type = 'image/png', size = 1024) => {
  const f = new File(['x'], name, { type })
  Object.defineProperty(f, 'size', { value: size })
  return f
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.uploadMock.mockResolvedValue({
    success: true,
    message: '识别到 2 项',
    filename: 'shot.png',
    item_count: 2,
    items: okItems,
    raw_text: '儿童保温杯500ml50箱',
    warnings: [],
  })
})

describe('useOcrPaste — 识别', () => {
  it('识别成功：填充候选条目并打开确认弹窗', async () => {
    const { ocr } = setup()
    await ocr.recognize(file())

    expect(ocr.draftItems.value).toHaveLength(2)
    expect(ocr.hasDrafts.value).toBe(true)
    expect(ocr.dialogOpen.value).toBe(true)
    expect(ocr.unmatchedCount.value).toBe(1)
    expect(ocr.sourceName.value).toBe('shot.png')
  })

  it('customer 参数必须拼进 URL（否则后端收不到，兜底客户失效）', async () => {
    const { ocr } = setup()
    await ocr.recognize(file())

    const url = mocks.uploadMock.mock.calls[0]![0] as string
    expect(url).toBe('/ocr-import/order/preview?customer=%E8%A1%A8%E5%8D%95%E5%AE%A2%E6%88%B7')
    expect(mocks.uploadMock.mock.calls[0]![1]).toBeInstanceOf(FormData)
  })

  it('识别 0 条：进指引态，并保留识别原文用于排查', async () => {
    mocks.uploadMock.mockResolvedValue({
      success: false,
      message: '没有识别到可导入的条目',
      filename: 'shot.png',
      item_count: 0,
      items: [],
      raw_text: '王姐，这周要补一批货',
      warnings: [],
    })
    const { ocr } = setup()
    await ocr.recognize(file())

    expect(ocr.dialogOpen.value).toBe(true)
    expect(ocr.hasDrafts.value).toBe(false)
    expect(ocr.rawText.value).toBe('王姐，这周要补一批货')
  })

  it('非图片非 PDF 被拒，不发请求', async () => {
    const { ocr } = setup()
    await ocr.recognize(file('a.doc', 'application/msword'))

    expect(mocks.uploadMock).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('请粘贴图片'), 'warning')
  })

  it('超过 10MB 被拒', async () => {
    const { ocr } = setup()
    await ocr.recognize(file('big.png', 'image/png', 11 * 1024 * 1024))

    expect(mocks.uploadMock).not.toHaveBeenCalled()
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('10MB'), 'warning')
  })

  it('并发触发只发一次请求', async () => {
    const { ocr } = setup()
    await Promise.all([ocr.recognize(file()), ocr.recognize(file())])
    expect(mocks.uploadMock).toHaveBeenCalledTimes(1)
  })

  it('请求失败时提示且不开弹窗', async () => {
    mocks.uploadMock.mockRejectedValue(new Error('boom'))
    const { ocr } = setup()
    await ocr.recognize(file())

    expect(ocr.dialogOpen.value).toBe(false)
    expect(ocr.draftItems.value).toHaveLength(0)
    // getErrorMessage 会优先用错误自身的信息，这里只断言「如实报错」而非具体文案
    const toast = vi.mocked(showToast)
    expect(toast).toHaveBeenCalledTimes(1)
    expect(toast.mock.calls[0]![1]).toBe('error')
  })
})

describe('useOcrPaste — 确认导入', () => {
  it('存在未匹配产品时拒绝导入，避免提交必然失败', async () => {
    const { ocr, collected } = setup()
    await ocr.recognize(file())

    const done = ocr.confirmImport()

    expect(done).toBe(false)
    expect(collected).toHaveLength(0)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('没有选择产品'), 'warning')
  })

  it('全部匹配后转成 origin=ocr 的前端暂存条目，客户与日期取表单值', async () => {
    mocks.uploadMock.mockResolvedValue({
      success: true,
      message: 'ok',
      filename: 'shot.png',
      item_count: 1,
      items: [okItems[0]],
      raw_text: '',
      warnings: [],
    })
    const { ocr, collected } = setup()
    await ocr.recognize(file())

    const done = ocr.confirmImport()

    expect(done).toBe(true)
    expect(collected).toHaveLength(1)
    expect(collected[0]).toMatchObject({
      origin: 'ocr',
      type: 'order',
      customer: '华东商贸',
      productId: 7,
      productName: '儿童保温杯 500ml',
      quantity: 50,
      date: '2026-09-29',
    })
    expect(ocr.dialogOpen.value).toBe(false)
    expect(ocr.draftItems.value).toHaveLength(0)
  })

  it('图上无客户时用表单已选客户兜底', async () => {
    mocks.uploadMock.mockResolvedValue({
      success: true,
      message: 'ok',
      filename: 'shot.png',
      item_count: 1,
      items: [{ ...okItems[0], customer: '', customer_id: null }],
      raw_text: '',
      warnings: [],
    })
    const { ocr, collected } = setup()
    await ocr.recognize(file())
    ocr.confirmImport()

    expect(collected[0]!.customer).toBe('表单客户')
  })
})

describe('useOcrPaste — 审核修复的闸门', () => {
  function okOne(over: Record<string, unknown> = {}) {
    mocks.uploadMock.mockResolvedValue({
      success: true, message: 'ok', filename: 'shot.png', item_count: 1,
      items: [{ ...okItems[0], ...over }], raw_text: '', warnings: [],
    })
  }

  it('数量为 0 时拒绝导入（手工路径有同一道闸门，此前 OCR 路径缺失）', async () => {
    okOne({ quantity: 0 })
    const { ocr, collected } = setup()
    await ocr.recognize(file())
    expect(ocr.invalidQuantityCount.value).toBe(1)
    expect(ocr.confirmImport()).toBe(false)
    expect(collected).toHaveLength(0)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('数量'), 'warning')
  })

  it('数量越界时拒绝导入', async () => {
    okOne({ quantity: 10_000_000 })
    const { ocr } = setup()
    await ocr.recognize(file())
    expect(ocr.invalidQuantityCount.value).toBe(1)
    expect(ocr.confirmImport()).toBe(false)
  })

  it('客户为空时拒绝导入', async () => {
    okOne({ customer: '', customer_id: null })
    // 表单也没选客户
    const collected: StagedItem[] = []
    const ocr = useOcrPaste({
      buildStaged: (drafts, ctx) => {
        collected.push(...buildOrderStagedItems(drafts, ctx))
        return true
      },
      getDefaultCustomer: () => '',
      getDefaultDate: () => '2026-09-29',
    })
    await ocr.recognize(file())
    expect(ocr.missingCustomerCount.value).toBe(1)
    expect(ocr.confirmImport()).toBe(false)
    expect(collected).toHaveLength(0)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('客户'), 'warning')
  })

  it('识别 0 条时 emptyResult 为真（指引态据此判断，而非条目数）', async () => {
    mocks.uploadMock.mockResolvedValue({
      success: false, message: 'none', filename: 's.png', item_count: 0,
      items: [], raw_text: '王姐，这周要补一批货', warnings: [],
    })
    const { ocr } = setup()
    await ocr.recognize(file())
    expect(ocr.emptyResult.value).toBe(true)
    expect(ocr.hasDrafts.value).toBe(false)
  })

  it('删光候选行不会把 emptyResult 变成真（不该报成识别失败）', async () => {
    const { ocr } = setup()
    await ocr.recognize(file())
    expect(ocr.emptyResult.value).toBe(false)
    ocr.draftItems.value = []
    expect(ocr.emptyResult.value).toBe(false)
    expect(ocr.hasDrafts.value).toBe(true)
  })

  it('上一次识别的条目不会残留到下一次', async () => {
    const { ocr } = setup()
    await ocr.recognize(file())
    expect(ocr.draftItems.value).toHaveLength(2)
    mocks.uploadMock.mockResolvedValue({
      success: true, message: 'ok', filename: 's2.png', item_count: 1,
      items: [okItems[0]], raw_text: '', warnings: ['图上有提示'],
    })
    await ocr.recognize(file('s2.png'))
    expect(ocr.draftItems.value).toHaveLength(1)
    expect(ocr.warnings.value).toEqual(['图上有提示'])
  })
})

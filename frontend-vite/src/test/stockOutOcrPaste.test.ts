/**
 * 出货页「粘贴图片识别 → 人工确认 → 进暂存区」行为测试。
 *
 * 与 customerOrderOcrPaste.test.ts 同构：识别与闸门在共享 useOcrPaste（已在订单侧覆盖），
 * 这里按 StockOutTab 的真实组合方式（buildStaged = buildStockoutStagedItems）
 * 锁死出货域自己的映射契约：
 *   1) product_id 转成字符串（StagedStockout 契约，与手工录入一致）
 *   2) 图上无客户时用表单已选客户兜底
 *   3) 闸门不过时不出条目
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
import { buildStockoutStagedItems } from '@/views/stock/composables/useStockoutOcrStaging'
import type { StagedStockout } from '@/types'

const okItem = {
  raw_product_name: '儿童保温杯500ml',
  product_id: 7,
  product_name: '儿童保温杯 500ml',
  match_confidence: 1,
  quantity: 50,
  unit: '箱',
  customer: '华东商贸',
  customer_id: 3,
  customer_confidence: 1,
  note: '物流发货',
}

function setup(collected: StagedStockout[] = []) {
  const ocr = useOcrPaste({
    buildStaged: (drafts, ctx) => {
      collected.push(...buildStockoutStagedItems(drafts, ctx))
      return true
    },
    getDefaultCustomer: () => '表单客户',
    getDefaultDate: () => '2026-10-06',
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
    message: '识别到 1 项',
    filename: 'shot.png',
    item_count: 1,
    items: [okItem],
    raw_text: '儿童保温杯500ml50箱',
    warnings: [],
  })
})

describe('buildStockoutStagedItems — 出货暂存映射', () => {
  it('确认后映射成暂存出货条目：product_id 转字符串，客户与日期取表单值', async () => {
    const { ocr, collected } = setup()
    await ocr.recognize(file())
    expect(ocr.confirmImport()).toBe(true)

    expect(collected).toHaveLength(1)
    expect(collected[0]).toMatchObject({
      product_id: '7',
      product_name: '儿童保温杯 500ml',
      customer: '华东商贸',
      date: '2026-10-06',
      quantity: 50,
      note: '物流发货',
    })
    expect(ocr.dialogOpen.value).toBe(false)
    expect(ocr.draftItems.value).toHaveLength(0)
  })

  it('图上无客户时用表单已选客户兜底', async () => {
    mocks.uploadMock.mockResolvedValue({
      success: true, message: 'ok', filename: 'shot.png', item_count: 1,
      items: [{ ...okItem, customer: '', customer_id: null }], raw_text: '', warnings: [],
    })
    const { ocr, collected } = setup()
    await ocr.recognize(file())
    ocr.confirmImport()

    expect(collected[0]!.customer).toBe('表单客户')
  })

  it('多行确认时 id 保持唯一', async () => {
    mocks.uploadMock.mockResolvedValue({
      success: true, message: 'ok', filename: 'shot.png', item_count: 2,
      items: [okItem, { ...okItem, product_id: 8, product_name: '卡通雨伞 8骨' }], raw_text: '', warnings: [],
    })
    const { ocr, collected } = setup()
    await ocr.recognize(file())
    ocr.confirmImport()

    expect(collected).toHaveLength(2)
    expect(new Set(collected.map((i) => i.id)).size).toBe(2)
  })
})

describe('useOcrPaste — 出货侧闸门', () => {
  it('未匹配产品时拒绝导入，不出条目', async () => {
    mocks.uploadMock.mockResolvedValue({
      success: true, message: 'ok', filename: 'shot.png', item_count: 1,
      items: [{ ...okItem, product_id: null }], raw_text: '', warnings: [],
    })
    const { ocr, collected } = setup()
    await ocr.recognize(file())

    expect(ocr.confirmImport()).toBe(false)
    expect(collected).toHaveLength(0)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('没有选择产品'), 'warning')
  })
})

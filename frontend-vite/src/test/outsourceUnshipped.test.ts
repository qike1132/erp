import { describe, it, expect, vi, beforeEach } from 'vitest'

const mocks = vi.hoisted(() => ({
  unshippedMock: vi.fn(),
  downloadXlsMock: vi.fn(),
  printHtmlMock: vi.fn(),
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}))

vi.mock('@/api/outsource', () => ({
  outsourceApi: { unshipped: mocks.unshippedMock },
}))
vi.mock('@/composables/useToast', () => ({ toast: mocks.toast }))
vi.mock('@/utils/xls', () => ({ downloadXls: mocks.downloadXlsMock }))
// 仅 mock printHtml（操作 DOM/iframe），保留真实 escapeHtml 供 buildUnshippedTbody 转义测试
vi.mock('@/utils/print', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...(actual as object), printHtml: mocks.printHtmlMock }
})

import { useOutsourceUnshipped, buildUnshippedTbody, UNSHIPPED_HEADERS } from '@/views/outsource/composables/useOutsourceUnshipped'
import type { UnshippedProcessItem } from '@/api/outsource'

function mkItem(over: Partial<UnshippedProcessItem> = {}): UnshippedProcessItem {
  return {
    order_id: 1,
    order_no: 'HB001',
    customer: '客户A',
    order_date: '2026-01-02 10:30',
    product_name: '产品A',
    product_barcode: '690001',
    process_type: '电绣',
    target_qty: 100,
    shipped_qty: 30,
    remaining: 70,
    ...over,
  }
}

const tdCount = (tr: string) => (tr.match(/<td/g) || []).length
const splitRows = (html: string) => html.split('</tr>').filter((s) => s.trim())

describe('未到货明细导出/打印同源（buildUnshippedTbody）', () => {
  it('表头不含「订单号」，列序与用户确认的截图一致', () => {
    expect(UNSHIPPED_HEADERS).toEqual([
      '客户', '下单时间', '产品名称', '产品条码', '工序', '订单数量', '已发数量', '未到数量',
    ])
    expect(UNSHIPPED_HEADERS).not.toContain('订单号')
  })

  it('单工序：每行输出 8 列，无 rowspan', () => {
    const html = buildUnshippedTbody([mkItem()])
    const rows = splitRows(html)
    expect(rows.length).toBe(1)
    expect(tdCount(rows[0]!)).toBe(8)
    expect(html).not.toContain('rowspan')
    expect(html).toContain('客户A')
    expect(html).toContain('产品A')
    expect(html).toContain('电绣')
    expect(html).toContain('>100<')
    expect(html).toContain('>30<')
    expect(html).toContain('>70<')
  })

  it('同 SKU 多工序：前 4 列 rowspan 合并到首行，工序/数量逐行输出', () => {
    const html = buildUnshippedTbody([
      mkItem({ process_type: '裁剪' }),
      mkItem({ process_type: '电绣' }),
      mkItem({ process_type: '缝制' }),
    ])
    const rows = splitRows(html)
    expect(rows.length).toBe(3)
    // 前 4 列各一个 rowspan="3"
    expect((html.match(/rowspan="3"/g) || []).length).toBe(4)
    // 首行 4 个合并列 + 4 个工序列 = 8；后续行只有 4 个工序列
    expect(tdCount(rows[0]!)).toBe(8)
    expect(tdCount(rows[1]!)).toBe(4)
    expect(tdCount(rows[2]!)).toBe(4)
    // 客户/产品信息只出现一次（被合并）
    expect((html.match(/客户A/g) || []).length).toBe(1)
    expect(html).toContain('裁剪')
    expect(html).toContain('缝制')
  })

  it('不同订单即使客户/产品相同也不合并（按 order_id 分组）', () => {
    const html = buildUnshippedTbody([
      mkItem({ order_id: 1, process_type: '裁剪' }),
      mkItem({ order_id: 2, process_type: '裁剪' }),
    ])
    expect(html).not.toContain('rowspan')
    expect((html.match(/客户A/g) || []).length).toBe(2)
  })

  it('产品条码单元格用 Excel 文本格式（避免长数字显示为科学计数法）', () => {
    const html = buildUnshippedTbody([mkItem({ product_barcode: '6978946330588' })])
    // 精确断言转义后的 CSS（mso-number-format:'\@'）
    expect(html).toContain(`mso-number-format:'\\@'`)
    expect(html).toContain('6978946330588')
  })

  it('字段含特殊字符时按 HTML 转义', () => {
    const html = buildUnshippedTbody([mkItem({ customer: '客<户>&"A' })])
    expect(html).toContain('客&lt;户&gt;&amp;&quot;A')
  })

  it('空值回退为 -', () => {
    const html = buildUnshippedTbody([mkItem({ order_date: null, product_name: null, product_barcode: null })])
    expect(html).toContain('>-<')
  })
})

describe('useOutsourceUnshipped 导出/打印行为', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('空数据：仅提示 warning，不导出、不弹成功（防回归：双提示）', async () => {
    mocks.unshippedMock.mockResolvedValue([])
    const { handleExport } = useOutsourceUnshipped()
    await handleExport()
    expect(mocks.toast.warning).toHaveBeenCalledWith('当前没有未到货（未发完）的工序')
    expect(mocks.downloadXlsMock).not.toHaveBeenCalled()
    expect(mocks.toast.success).not.toHaveBeenCalled()
  })

  it('有数据：导出 XLS 并弹成功', async () => {
    mocks.unshippedMock.mockResolvedValue([mkItem()])
    const { handleExport } = useOutsourceUnshipped()
    await handleExport()
    expect(mocks.downloadXlsMock).toHaveBeenCalledTimes(1)
    expect(mocks.toast.success).toHaveBeenCalledWith('导出成功')
  })

  it('打印：调用 printHtml 并弹成功提示（条数）', async () => {
    mocks.unshippedMock.mockResolvedValue([mkItem(), mkItem({ order_id: 2, order_no: 'HB002' })])
    const { handlePrint } = useOutsourceUnshipped()
    await handlePrint()
    expect(mocks.printHtmlMock).toHaveBeenCalledTimes(1)
    expect(mocks.toast.success).toHaveBeenCalledWith('已发送 2 条未到货明细至打印预览')
  })

  it('接口失败：仅提示 error，不导出', async () => {
    mocks.unshippedMock.mockRejectedValue(new Error('network'))
    const { handleExport } = useOutsourceUnshipped()
    await handleExport()
    expect(mocks.toast.error).toHaveBeenCalledWith('加载未到货明细失败')
    expect(mocks.downloadXlsMock).not.toHaveBeenCalled()
  })
})

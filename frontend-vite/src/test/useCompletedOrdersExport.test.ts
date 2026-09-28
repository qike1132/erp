/**
 * 记录查询导出回归测试。
 *
 * 历史缺陷：后端 `/orders/completed/export` 返回的是 rows 明细行，
 * 前端却仍按旧的 html 契约取值，导致点击“导出”必定抛「导出失败」。
 * 本测试锁定“按 rows 拼表并下载”的契约。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mocks = vi.hoisted(() => ({
  exportCompleted: vi.fn(),
}))

vi.mock('@/api', () => ({
  purchaseApi: {
    completed: vi.fn(),
    exportCompleted: mocks.exportCompleted,
  },
}))

// 被测 composable 依赖 Vue Query 上下文；此处只提供最小可用替身
vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  return {
    useQuery: () => ({
      data: ref(null),
      isLoading: ref(false),
      isFetching: ref(false),
      isError: ref(false),
    }),
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    keepPreviousData: {},
  }
})

import { effectScope } from 'vue'
import { useCompletedOrders } from '@/views/purchase/composables/useCompletedOrders'

let capturedParts: BlobPart[] | undefined
let capturedFilename: string | undefined
const clickSpy = vi.fn()

function runComposable() {
  const scope = effectScope()
  const instance = scope.run(() => useCompletedOrders())
  if (!instance) throw new Error('composable 未返回实例')
  return instance
}

beforeEach(() => {
  capturedParts = undefined
  capturedFilename = undefined
  mocks.exportCompleted.mockReset()

  const RealBlob = globalThis.Blob
  vi.stubGlobal(
    'Blob',
    class {
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        capturedParts = parts
        return new RealBlob(parts, options)
      }
    },
  )
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:mock-url'),
    revokeObjectURL: vi.fn(),
  })

  clickSpy.mockClear()
  const origCreate = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    const el = origCreate(tag)
    if (tag === 'a') {
      ;(el as HTMLAnchorElement).click = function () {
        capturedFilename = (this as HTMLAnchorElement).download
        clickSpy()
      }
    }
    return el
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('useCompletedOrders 导出', () => {
  it('按后端 rows 拼成表格并触发 .xls 下载（不再依赖 html 字段）', async () => {
    mocks.exportCompleted.mockResolvedValue({
      success: true,
      rows: [
        {
          order_no: 'CG-20260927-0012',
          completed_at: '2026-09-27',
          customer_name: '甲&乙',
          supplier_name: '供<应>商',
          material_name: '面料',
          material_code: 'M001',
          specification: '规格',
          unit: '码',
          quantity: 10.5,
          unit_price: 2,
          amount: 21,
        },
      ],
    })

    await runComposable().exportOrders()

    expect(mocks.exportCompleted).toHaveBeenCalledTimes(1)
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(capturedFilename).toBe('记录查询汇总.xls')
    const html = String(capturedParts?.[0])
    // 表头与数据齐全
    expect(html).toContain('<th>订单号</th>')
    expect(html).toContain('<th>材料名称</th>')
    expect(html).toContain('<td>CG-20260927-0012</td>')
    expect(html).toContain('<td>10.5</td>')
    // 单元格必须转义，避免物料名里的尖括号/& 破坏表格结构
    expect(html).toContain('<td>甲&amp;乙</td>')
    expect(html).toContain('<td>供&lt;应&gt;商</td>')
  })

  it('空 rows 抛错且不触发下载', async () => {
    mocks.exportCompleted.mockResolvedValue({ success: true, rows: [] })

    await expect(runComposable().exportOrders()).rejects.toThrow('没有符合条件的数据可导出')
    expect(clickSpy).not.toHaveBeenCalled()
  })

  it('success=false 时透出后端 message', async () => {
    mocks.exportCompleted.mockResolvedValue({ success: false, message: '无导出权限' })

    await expect(runComposable().exportOrders()).rejects.toThrow('无导出权限')
    expect(clickSpy).not.toHaveBeenCalled()
  })
})

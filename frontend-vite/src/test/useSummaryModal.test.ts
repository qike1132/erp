/**
 * 备品数量（备品数量列）单元测试
 *
 * 覆盖：
 * 1. calcSpareQuantity 纯函数全部边界（lossRate=0 / 正常 / 1000 / 小数 / 非法输入）
 * 2. getGroupOrderQty 订单数量取数（product_quantity 优先 / order_quantity 回退 / 非法兜底 0）
 * 3. buildFactoryHtml 打印/导出共用 HTML：9 列表头 + 数据行第 4 列备品数量、第 8 列数量
 * 4. SummaryModal 挂载后 spareQuantityGrandTotal 合计口径 = 各 group ceil 后累加，
 *    合计行按表头列位对齐（第 4 列备品数量合计、第 8 列数量合计），
 *    以及数据行备品数量与合计口径一致（含字符串 qty 的防御性 parseFloat 场景）
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

// 隔离外部依赖：useSummaryModal.ts 顶层 import purchaseApi from '@/api'，
// 测试不发起真实请求，用最小 stub 替换即可。
vi.mock('@/api', () => ({
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: vi.fn(),
    supplierSummaryExport: vi.fn(),
  },
}))

import { calcSpareQuantity, getGroupOrderQty, buildFactoryHtml } from '@/views/purchase/composables/useSummaryModal'
import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import { fmtQty } from '@/utils/formatQty'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

// reka-ui 的 Dialog 依赖 teleport/portal，jsdom 下直接 stub 成普通容器渲染插槽内容更稳。
// FontAwesomeIcon 已由 src/test/setup.ts 全局 stub。
const stubs = {
  UiDialog: {
    template: '<div class="ui-dialog-stub"><slot name="title" /><slot /></div>',
  },
}

interface CellLike {
  text(): string
  attributes(name: string): string | undefined
}

/** 按 colspan 展开为逻辑列，便于与表头列位（1客户/…/9单位）对齐断言合计行 */
function expandColspan(cells: CellLike[]): string[] {
  const cols: string[] = []
  cells.forEach((cell) => {
    const span = Number(cell.attributes('colspan')) || 1
    const text = cell.text()
    for (let i = 0; i < span; i++) cols.push(text)
  })
  return cols
}

describe('calcSpareQuantity 纯函数', () => {
  it('lossRate=0 → 0', () => {
    expect(calcSpareQuantity(100, 0)).toBe(0)
  })

  it('lossRate=5, qty=100 → ceil(0.5)=1', () => {
    expect(calcSpareQuantity(100, 5)).toBe(1)
  })

  it('lossRate=1000, qty=1 → ceil(1)=1', () => {
    expect(calcSpareQuantity(1, 1000)).toBe(1)
  })

  it('lossRate=3, qty=100 → ceil(0.3)=1', () => {
    expect(calcSpareQuantity(100, 3)).toBe(1)
  })

  it('小数 qty=0.5, lossRate=5 → ceil(0.0025)=1', () => {
    expect(calcSpareQuantity(0.5, 5)).toBe(1)
  })

  it('qty=999.9, lossRate=1 → ceil(0.9999)=1', () => {
    expect(calcSpareQuantity(999.9, 1)).toBe(1)
  })

  it('非法 qty → 0（undefined/NaN/0/负数/Infinity）', () => {
    expect(calcSpareQuantity(undefined as unknown as number, 5)).toBe(0)
    expect(calcSpareQuantity(NaN, 5)).toBe(0)
    expect(calcSpareQuantity(0, 5)).toBe(0)
    expect(calcSpareQuantity(-10, 5)).toBe(0)
    expect(calcSpareQuantity(Infinity, 5)).toBe(0)
  })

  it('非法 lossRate → 0（NaN/负数）', () => {
    expect(calcSpareQuantity(100, NaN)).toBe(0)
    expect(calcSpareQuantity(100, -1)).toBe(0)
  })
})

describe('SummaryModal 备品数量合计口径', () => {
  const factoryData: FactorySummaryData = {
    success: true,
    order_count: 2,
    groups: [
      {
        customer_name: '客户A',
        product_name: '产品1',
        product_quantity: 100,
        suppliers: [
          {
            supplier_name: '供应商1',
            fabrics: [
              { fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米' },
              { fabric_name: '布料B', specification: 'S2', quantity: 20, unit: '米' },
            ],
          },
        ],
      },
      {
        customer_name: '客户B',
        product_name: '产品2',
        order_quantity: 50,
        suppliers: [
          {
            supplier_name: '供应商2',
            fabrics: [{ fabric_name: '布料C', specification: 'S3', quantity: 5, unit: '米' }],
          },
        ],
      },
    ],
  }

  function mountModal(lossRate: number, data: FactorySummaryData = factoryData) {
    return mount(SummaryModal, {
      props: {
        open: true,
        factoryData: data,
        supplierData: null,
        editMode: false,
        lossRate,
        orderCount: 2,
        supplierGroups: [],
      },
      global: { stubs },
    })
  }

  it('工厂表格表头含 9 列且第 4 列为「备品数量」', () => {
    const wrapper = mountModal(0)
    const headers = wrapper.findAll('thead th').map((th) => th.text())
    expect(headers).toHaveLength(9)
    expect(headers[3]).toBe('备品数量')
  })

  it('合计行按表头列位对齐：第 4 列备品数量合计、第 8 列数量合计（lossRate=5）', () => {
    // 备品合计：group0 ceil(100*5/1000)=1；group1 ceil(50*5/1000)=1 → 2
    // 数量合计：10+20+5 = 35
    const wrapper = mountModal(5)
    const rows = wrapper.findAll('tbody tr')
    const totalCols = expandColspan(rows[rows.length - 1]!.findAll('td'))
    expect(totalCols[3]).toBe(fmtQty(2)) // 第4列 备品数量
    expect(totalCols[7]).toBe(fmtQty(35)) // 第8列 数量
  })

  it('数据行备品数量与合计口径一致（lossRate=0 → 全 0）', () => {
    const wrapper = mountModal(0)
    const rows = wrapper.findAll('tbody tr')
    const totalCols = expandColspan(rows[rows.length - 1]!.findAll('td'))
    expect(totalCols[3]).toBe(fmtQty(0)) // 第4列 备品数量合计
    expect(totalCols[7]).toBe(fmtQty(35)) // 第8列 数量合计（lossRate=0 不改变数量）
    // 首行客户×产品行的备品数量单元格（第 4 列）也为 0
    expect(rows[0]!.findAll('td')[3]!.text()).toBe(fmtQty(0))
  })

  it('字符串 qty 也能正确计算（防御性 parseFloat，回归 QA 发现的行内显示 0 问题）', () => {
    const data: FactorySummaryData = {
      success: true,
      order_count: 1,
      groups: [
        {
          customer_name: '客户A',
          product_name: '产品1',
          product_quantity: '100' as unknown as number,
          suppliers: [
            {
              supplier_name: '供应商1',
              fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米' }],
            },
          ],
        },
      ],
    }
    const wrapper = mountModal(5, data)
    const rows = wrapper.findAll('tbody tr')
    const firstRowCells = rows[0]!.findAll('td')
    // 客户/产品名称/订单数量/备品数量 → 第 4 列应为 ceil(100*5/1000)=1，而非 0
    expect(firstRowCells[3]!.text()).toBe(fmtQty(1))
  })
})

describe('getGroupOrderQty 订单数量取数', () => {
  const baseGroup: FactorySummaryData['groups'][number] = { customer_name: '客户A', product_name: '产品1', suppliers: [] }

  it('product_quantity 优先', () => {
    expect(getGroupOrderQty({ ...baseGroup, product_quantity: 100 })).toBe(100)
  })

  it('缺 product_quantity 时回退 order_quantity', () => {
    expect(getGroupOrderQty({ ...baseGroup, order_quantity: 50 })).toBe(50)
  })

  it('字符串 qty 也能解析（防御性 parseFloat）', () => {
    expect(getGroupOrderQty({ ...baseGroup, product_quantity: '100' as unknown as number })).toBe(100)
  })

  it('非法/缺失 → 0', () => {
    expect(getGroupOrderQty({ ...baseGroup, product_quantity: 'abc' as unknown as number })).toBe(0)
    expect(getGroupOrderQty({ ...baseGroup })).toBe(0)
  })
})

describe('buildFactoryHtml 打印/导出共用 HTML', () => {
  const minimalData: FactorySummaryData = {
    success: true,
    order_count: 1,
    groups: [
      {
        customer_name: '客户X',
        product_name: '产品X',
        product_quantity: 100,
        suppliers: [
          {
            supplier_name: '供应商X',
            fabrics: [{ fabric_name: '布料X', specification: 'SX', quantity: 10, unit: '米' }],
          },
        ],
      },
    ],
  }

  // buildFactoryHtml 只输出 tbody 行，表头由 printFactory/exportFactory 按同一 9 列拼装；测试按相同方式包裹。
  function wrapFactoryHtml(data: FactorySummaryData, lossRate: number): string {
    return `<table><thead><tr><th>客户</th><th>产品名称</th><th>订单数量</th><th>备品数量</th><th>供应商</th><th>布料名称</th><th>规格型号</th><th>数量</th><th>单位</th></tr></thead><tbody>${buildFactoryHtml(data, lossRate)}</tbody></table>`
  }

  it('表头含 9 个 th 且第 4 个为「备品数量」；数据行第 4 列 = 备品数量、第 8 列 = 数量、第 9 列 = 单位', () => {
    const doc = new DOMParser().parseFromString(wrapFactoryHtml(minimalData, 5), 'text/html')
    const headers = [...doc.querySelectorAll('thead th')].map((th) => th.textContent || '')
    expect(headers).toHaveLength(9)
    expect(headers[3]).toBe('备品数量')

    const firstRow = doc.querySelector('tbody tr')!
    const cells = [...firstRow.querySelectorAll('td')]
    // 1客户/2产品名称/3订单数量/4备品数量/5供应商/6布料名称/7规格型号/8数量/9单位
    expect(cells[3]!.textContent).toBe(fmtQty(1)) // ceil(100*5/1000)=1
    expect(cells[7]!.textContent).toBe(fmtQty(10)) // 数量
    expect(cells[8]!.textContent).toBe('米') // 单位
  })

  it('lossRate=0 时备品数量列为 0（口径与屏幕表格一致）', () => {
    const doc = new DOMParser().parseFromString(wrapFactoryHtml(minimalData, 0), 'text/html')
    const row = doc.querySelector('tbody tr')!
    const cells = [...row.querySelectorAll('td')]
    expect(cells[3]!.textContent).toBe(fmtQty(0))
  })
})

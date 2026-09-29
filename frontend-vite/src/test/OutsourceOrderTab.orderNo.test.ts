/**
 * 外发订单列表：订单号列回归锁（2026-09-29）。
 *
 * 外发页**从未有过**订单号列（与贝乐页不同，那边是被改版换掉的）。
 * 现按变体 B 新增：保留「订单类型」，订单号紧随其后。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({ row: {} as Record<string, unknown> }))

vi.mock('@/views/outsource/composables/useOutsourceOrders', () => ({
  useOutsourceOrders: () => ({
    PAGE_SIZE_OPTIONS: [18],
    perPage: ref(18),
    currentPage: ref(1),
    isLoading: ref(false),
    isFetching: ref(false),
    refetch: vi.fn(),
    orders: ref([mocks.row]),
    totalItems: ref(1),
    totalPages: ref(1),
    visibleSkus: () => [],
    displayOrders: ref([mocks.row]),
    totalQuantity: () => 30,
    goPage: vi.fn(),
  }),
}))

import OutsourceOrderTab from '@/views/outsource/components/OutsourceOrderTab.vue'

function mountTab() {
  return mount(OutsourceOrderTab, {
    props: { productFilter: '', customerFilter: '' },
    global: { stubs: { OutsourceProcessDialog: true, UiPagination: true } },
  })
}

describe('OutsourceOrderTab 订单号列', () => {
  beforeEach(() => {
    mocks.row = {
      id: 1,
      record_type: 'order',
      order_no: 'PO-20260929-0008',
      order_date: '2026-09-29',
      customer: 'MINISO国内',
      product_name: 'X',
      quantity: 30,
      total_processes: 0,
      progress: 0,
      factories: ['湖北'],
    }
  })

  it('表头含「订单号」且紧随「订单类型」之后', () => {
    const headers = mountTab().findAll('th').map((t) => t.text())
    expect(headers).toContain('订单类型')
    expect(headers).toContain('订单号')
    expect(headers.indexOf('订单号')).toBe(headers.indexOf('订单类型') + 1)
  })

  it('行内渲染订单号', () => {
    expect(mountTab().text()).toContain('PO-20260929-0008')
  })

  it('备货行同样显示订单号', () => {
    mocks.row = { ...mocks.row, record_type: 'stockin', order_no: 'BH-20260929-0001' }
    expect(mountTab().text()).toContain('BH-20260929-0001')
  })
})

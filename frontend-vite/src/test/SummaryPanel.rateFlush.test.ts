/**
 * 损耗率输入「防抖窗口不丢值」回归（2026-11-28 生产事故）。
 *
 * 事故：用户输入自定义损耗率后刷新页面，最终输入的值被 300ms 防抖
 * onUnmounted 作废——请求根本没发出，刷新后回显旧值（「无法持久化」）。
 *
 * 本文件守四件事：
 *  1. 失焦立即 flush 挂起值（不等 300ms），且定时器作废不双发；
 *  2. 防抖合并语义不变：300ms 内连续输入只发最后一次；
 *  3. 「返回订单列表」先 flush 挂起率再 emit close（顺序即验收标准：
 *     close 之后 composable 会作废 orderIds，晚到请求带不上单号）；
 *  4. 布料行率同样支持失焦立即提交。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'

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

import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

/** 单组单供应商单布料，带 item_ids（行率输入的可编辑前提）。 */
const FACTORY: FactorySummaryData = {
  success: true,
  order_count: 1,
  groups: [{
    customer_name: '客户甲',
    product_name: '产品',
    product_quantity: 100,
    suppliers: [{
      supplier_name: '供应商甲',
      fabrics: [{ fabric_name: '宝乐绒', specification: 'S1', quantity: 50, unit: '米', item_ids: [1] }],
    }],
  }],
}

function mountPanel() {
  return mount(SummaryPanel, {
    props: {
      factoryData: FACTORY,
      supplierData: null,
      lossRate: 5,
      orderCount: 1,
      supplierGroups: [],
    },
  })
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('统一损耗率：失焦立即提交', () => {
  it('输入后 300ms 内失焦 → 立即 emit applyLossRate，且定时器作废不双发', async () => {
    const w = mountPanel()
    const input = w.find('thead th.sm-rate-head input[type="number"]')

    await input.setValue('12')

    // 未到 300ms 就失焦：挂起值必须立刻提交
    await input.trigger('blur')
    expect(w.emitted('applyLossRate')).toEqual([[12]])

    // 定时器已作废：时间走完也不得再发（否则同值双写）
    await vi.advanceTimersByTimeAsync(500)
    expect(w.emitted('applyLossRate')).toHaveLength(1)
    w.unmount()
  })

  it('失焦时无挂起值（只聚焦未输入）→ 空操作不 emit', async () => {
    const w = mountPanel()
    await w.find('thead th.sm-rate-head input[type="number"]').trigger('blur')
    expect(w.emitted('applyLossRate')).toBeUndefined()
    w.unmount()
  })

  it('防抖合并语义不变：300ms 内连续输入只发最后一次', async () => {
    const w = mountPanel()
    const input = w.find('thead th.sm-rate-head input[type="number"]')

    await input.setValue('10')
    await input.setValue('15')
    await input.setValue('20')
    await vi.advanceTimersByTimeAsync(400)

    const calls = w.emitted('applyLossRate') || []
    expect(calls).toEqual([[20]])
    w.unmount()
  })
})

describe('布料行损耗率：失焦立即提交', () => {
  it('行率输入后失焦 → emit applyFabricLossRate 携带该行落库坐标与最新值', async () => {
    const w = mountPanel()
    const rowInput = w.find('tbody input[type="number"]')
    expect(rowInput.exists()).toBe(true)

    await rowInput.setValue('33')
    await rowInput.trigger('blur')

    expect(w.emitted('applyFabricLossRate')).toEqual([[0, 0, 0, 33]])

    await vi.advanceTimersByTimeAsync(500)
    expect(w.emitted('applyFabricLossRate')).toHaveLength(1)
    w.unmount()
  })
})

describe('返回订单列表：先 flush 再 close', () => {
  it('挂起的统一率在 close 之前提交（晚提交会带不上采购单号）', async () => {
    const onApplyLossRate = vi.fn()
    const onClose = vi.fn()
    const w = mount(SummaryPanel, {
      props: {
        factoryData: FACTORY,
        supplierData: null,
        lossRate: 5,
        orderCount: 1,
        supplierGroups: [],
      },
      attrs: { onApplyLossRate, onClose },
    })

    await w.find('thead th.sm-rate-head input[type="number"]').setValue('20')
    // 未等防抖到点，直接点返回
    await w.find('.sm-back-btn').trigger('click')

    expect(onApplyLossRate).toHaveBeenCalledTimes(1)
    expect(onApplyLossRate).toHaveBeenCalledWith(20)
    expect(onClose).toHaveBeenCalledTimes(1)
    // 顺序是验收标准：flush 的 save 请求必须赶在 close 作废 orderIds 之前发出
    expect(onApplyLossRate.mock.invocationCallOrder[0]).toBeLessThan(onClose.mock.invocationCallOrder[0]!)
    w.unmount()
  })
})

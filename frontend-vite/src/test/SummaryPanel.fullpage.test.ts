/**
 * 汇总下单**整页视图**（2026-10-31 由弹窗改铺满内容区）的行为级测试。
 *
 * 前身是 SummaryModal.overlay.test.ts（弹窗「遮罩不关闭」），UiDialog 外壳删除后
 * 遮罩交互不复存在、原用例随之作废。本文件覆盖整页化后的三个新契约：
 *
 * 1. 【布局】SummaryPanel 不再包 UiDialog：根节点是普通 div（无 role="dialog"），
 *    且头部含「返回订单列表」按钮（弹窗时代的「关闭」语义改名）。
 * 2. 【返回】点头部/底部返回按钮 → emit close（由 PurchaseView 决定是否确认）。
 * 3. 【离开守卫】useSummaryLeaveGuard：非脏态放行（true）；脏态走确认，
 *    确认/取消分别对应放行+close / 拦截——守卫本身不弹 UI，UI 由调用方注入。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

// 隔离外部依赖：SummaryPanel → 子组件 → useSummaryModal 顶层 import purchaseApi from '@/api'
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
import { useSummaryLeaveGuard } from '@/views/purchase/composables/useSummaryLeaveGuard'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

const FACTORY: FactorySummaryData = {
  success: true,
  order_count: 1,
  groups: [
    {
      customer_name: '客户A',
      product_name: '产品1',
      product_quantity: 100,
      suppliers: [
        {
          supplier_name: '供应商1',
          fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米' }],
        },
      ],
    },
  ],
}

function mountPanel() {
  return mount(SummaryPanel, {
    props: {
      factoryData: FACTORY,
      supplierData: null,
      editMode: false,
      lossRate: 5,
      orderCount: 1,
      supplierGroups: [],
    },
  })
}

describe('整页布局契约（弹窗 → 页面视图）', () => {
  it('根节点不再是 dialog：无 role="dialog"，无遮罩', () => {
    const w = mountPanel()
    expect(w.find('[role="dialog"]').exists()).toBe(false)
    expect(w.attributes('role')).toBeUndefined()
    w.unmount()
  })

  it('头部含「汇总下单」标题与「返回订单列表」按钮', () => {
    const w = mountPanel()
    expect(w.find('.sm-title').text()).toContain('汇总下单')
    const back = w.find('.sm-back-btn')
    expect(back.exists()).toBe(true)
    expect(back.text()).toContain('返回订单列表')
    w.unmount()
  })

  it('页签按钮与页签切换（工厂默认激活）', async () => {
    const w = mountPanel()
    const tabs = w.findAll('.sm-tab-btn')
    expect(tabs).toHaveLength(2)
    expect(tabs[0]!.text()).toContain('工厂内部订单')
    expect(tabs[0]!.classes()).toContain('active')
    expect(tabs[1]!.text()).toContain('供应商采购订单')
    w.unmount()
  })

  it('两个页签都不渲染时（supplierData 为 null 切到供应商页签）不抛错', async () => {
    const w = mountPanel()
    await w.findAll('.sm-tab-btn')[1]!.trigger('click')
    // 供应商页签 v-if="supplierData" → 无内容渲染但不崩
    expect(w.findAll('.sm-tab-btn')[1]!.classes()).toContain('active')
    expect(w.find('table').exists()).toBe(false)
    w.unmount()
  })
})

describe('返回按钮 → close 事件链', () => {
  it('点头部「返回订单列表」→ emit close', async () => {
    const w = mountPanel()
    await w.find('.sm-back-btn').trigger('click')
    expect(w.emitted('close')).toBeTruthy()
    expect(w.emitted('close')!.length).toBe(1)
    w.unmount()
  })

  it('点工厂页签底部「返回订单列表」→ emit close（经 Panel 转发）', async () => {
    const w = mountPanel()
    const backBtn = w.findAll('button').find((b) => b.text().includes('返回订单列表') && !b.classes().includes('sm-back-btn'))
    expect(backBtn).toBeTruthy()
    await backBtn!.trigger('click')
    expect(w.emitted('close')).toBeTruthy()
    w.unmount()
  })
})

/**
 * onBeforeRouteLeave 由 useSummaryLeaveGuard 在 setup 内注册，这里捕获它。
 * vi.mock 会被 hoist 到文件顶，registeredGuards 必须用 var（hoist 后仍可访问）。
 */
const registeredGuards: Array<() => unknown> = []
vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    onBeforeRouteLeave: (guard: () => unknown) => { registeredGuards.push(guard) },
  }
})

describe('useSummaryLeaveGuard：编辑态离开确认', () => {
  function setup(summaryState: {
    open?: boolean
    editMode?: boolean
    lossRateTouched?: boolean
    lossRateSaveState?: 'idle' | 'saving' | 'saved' | 'error'
  } = {}, confirmResult = true) {
    registeredGuards.length = 0
    const confirm = vi.fn(() => Promise.resolve(confirmResult))
    const summary = {
      open: summaryState.open ?? true,
      editMode: summaryState.editMode ?? false,
      lossRateTouched: summaryState.lossRateTouched ?? false,
      lossRateSaveState: summaryState.lossRateSaveState ?? 'idle',
      close: vi.fn(),
    }
    const { handleSummaryClose } = useSummaryLeaveGuard(summary as never, confirm)
    const guard = registeredGuards[0] as () => Promise<boolean | undefined>
    return { guard, confirm, summary, handleSummaryClose }
  }

  it('非脏态：直接放行，不弹确认', async () => {
    const { guard, confirm } = setup({})
    await expect(guard()).resolves.toBe(true)
    expect(confirm).not.toHaveBeenCalled()
  })

  it('脏态（editMode）+ 用户确认 → 放行并 close', async () => {
    const { guard, confirm, summary } = setup({ editMode: true }, true)
    await expect(guard()).resolves.toBe(true)
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(summary.close).toHaveBeenCalled()
  })

  it('脏态（损耗率在途）+ 用户取消 → 拦截（false）、不 close', async () => {
    const { guard, confirm, summary } = setup({ lossRateTouched: true }, false)
    await expect(guard()).resolves.toBe(false)
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(summary.close).not.toHaveBeenCalled()
  })

  it('弹窗未打开（open=false）即使脏字段残留也放行', async () => {
    const { guard, confirm } = setup({ open: false, editMode: true }, true)
    await expect(guard()).resolves.toBe(true)
    expect(confirm).not.toHaveBeenCalled()
  })

  it('handleSummaryClose：非脏态直接 close 不确认', async () => {
    const { handleSummaryClose, confirm, summary } = setup({})
    await handleSummaryClose()
    expect(confirm).not.toHaveBeenCalled()
    expect(summary.close).toHaveBeenCalled()
  })

  it('handleSummaryClose：脏态取消时不 close', async () => {
    const { handleSummaryClose, confirm, summary } = setup({ editMode: true }, false)
    await handleSummaryClose()
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(summary.close).not.toHaveBeenCalled()
  })
})

/**
 * OutsourceShipCartPanel 右栏子组件测试
 *
 * 清单渲染 + 单元格交互：数量纠正（小数取整/0 恢复上限/超限钳制）、
 * 校验样式（is-invalid / is-off）、卡头合计口径（rowQty：未勾选/非法记 0）、
 * 事件上抛（remove / clear）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import OutsourceShipCartPanel from '@/views/outsource/components/OutsourceShipCartPanel.vue'
import type { CartProduct, CartProcessRow, MergedInput } from '@/views/outsource/components/shipCartModel'
import type { ShippableProcessItem } from '@/api/outsource'

function entry(over: Partial<ShippableProcessItem> = {}): ShippableProcessItem {
  const remaining = over.remaining ?? 100
  return {
    process_id: 1, order_id: 1, order_no: 'PO-A', customer: '客户A',
    product_name: 'SKU-A', process_type: '电绣',
    target_qty: remaining + (over.shipped_qty ?? 0),
    shipped_qty: 0, remaining,
    ...over,
  }
}

function procRow(over: {
  processType?: string; qty?: number; on?: boolean
  remaining?: number; entries?: ShippableProcessItem[]
} = {}): CartProcessRow {
  const input: MergedInput = { qty: over.qty ?? 0, on: over.on ?? true }
  return {
    key: `K-${over.processType ?? '电绣'}`, processType: over.processType ?? '电绣',
    entries: over.entries ?? [entry({ remaining: over.remaining })],
    targetQty: over.remaining ?? 100, remaining: over.remaining ?? 100,
    input,
  }
}

function cartProduct(over: {
  productName?: string; processes?: CartProcessRow[]; orderIds?: number[]
} = {}): CartProduct {
  const productName = over.productName ?? 'SKU-A'
  return {
    key: productName, productName,
    orderIds: over.orderIds ?? [1],
    processes: over.processes ?? [procRow()],
  }
}

function mountPanel(groups: CartProduct[]) {
  return mount(OutsourceShipCartPanel, {
    props: { groups },
    global: { stubs: { FontAwesomeIcon: { template: '<i />' } } },
  })
}

describe('OutsourceShipCartPanel 右栏清单', () => {
  it('空清单显示空态与「0 项」，清空按钮禁用', () => {
    const wrapper = mountPanel([])
    expect(wrapper.find('.osw-cart-empty').text()).toContain('发货清单还是空的')
    expect(wrapper.find('.osw-chip').text()).toContain('0 项')
    expect(wrapper.find('.osw-r-head .osw-link').attributes('disabled')).toBeDefined()
  })

  it('渲染产品卡：标题、合并单数角标、工序格与数量框', () => {
    const wrapper = mountPanel([cartProduct({
      orderIds: [1, 2],
      processes: [procRow({ processType: '电绣', qty: 100 }), procRow({ processType: '转印', qty: 50 })],
    })])
    expect(wrapper.find('.osw-chip').text()).toContain('1 项')
    expect(wrapper.find('.osw-cart-title').text()).toBe('SKU-A')
    expect(wrapper.find('.osw-cart-orders').text()).toBe('2 单合并')
    expect(wrapper.findAll('.osw-cell').map((c) => c.find('.osw-proc').text())).toEqual(['电绣', '转印'])
    expect(wrapper.findAll('.osw-qty').length).toBe(2)
  })

  it('卡头合计按 rowQty 口径：未勾选与非法行记 0', () => {
    const wrapper = mountPanel([cartProduct({
      processes: [
        procRow({ processType: '电绣', qty: 60 }),
        procRow({ processType: '转印', qty: 999, on: false, remaining: 50 }),
        procRow({ processType: '缝制', qty: 0, remaining: 50 }),
      ],
    })])
    // 60 + 0（未勾选） + 0（0 为非法） = 60
    expect(wrapper.find('.osw-cart-sum').text()).toContain('60')
  })

  it('实时剩余：发完后剩余 = 剩余合计 − 本次填写；未勾选不扣减', () => {
    const wrapper = mountPanel([cartProduct({
      processes: [procRow({ qty: 30, remaining: 100 }), procRow({ processType: '转印', qty: 100, on: false, remaining: 100 })],
    })])
    const remains = wrapper.findAll('.osw-remain b')
    expect(remains[0]!.text()).toBe('70')
    expect(remains[1]!.text()).toBe('100')
  })

  it('数量输入纠正：小数向下取整写回输入框', async () => {
    const wrapper = mountPanel([cartProduct()])
    const qty = wrapper.find('.osw-qty')
    await qty.setValue('1.5')
    expect((qty.element as HTMLInputElement).value).toBe('1')
    await qty.setValue('1.9')
    expect((qty.element as HTMLInputElement).value).toBe('1')
  })

  it('数量输入纠正：0/负数恢复为剩余上限', async () => {
    const wrapper = mountPanel([cartProduct()])
    const qty = wrapper.find('.osw-qty')
    await qty.setValue(0)
    expect((qty.element as HTMLInputElement).value).toBe('100')
    await qty.setValue(-5)
    expect((qty.element as HTMLInputElement).value).toBe('100')
  })

  it('数量输入纠正：超限钳制到上限且不进入非法态', async () => {
    const wrapper = mountPanel([cartProduct()])
    const qty = wrapper.find('.osw-qty')
    await qty.setValue(999)
    expect((qty.element as HTMLInputElement).value).toBe('100')
    expect(qty.classes()).not.toContain('is-invalid')
  })

  it('清空输入框不纠正（允许中途重填）', async () => {
    const wrapper = mountPanel([cartProduct({ processes: [procRow({ qty: 30 })] })])
    const qty = wrapper.find('.osw-qty')
    await qty.setValue('')
    expect((qty.element as HTMLInputElement).value).toBe('')
  })

  it('取消勾选：整格带 is-off、数量框禁用；✕ 与清空分别上抛事件', async () => {
    const wrapper = mountPanel([cartProduct({ processes: [procRow({ qty: 30 })] })])
    await wrapper.find('.osw-cell .osw-cbx').setValue(false)
    expect(wrapper.find('.osw-cell').classes()).toContain('is-off')
    expect(wrapper.find('.osw-qty').attributes('disabled')).toBeDefined()

    await wrapper.find('.osw-rm').trigger('click')
    expect(wrapper.emitted('remove')![0]).toEqual(['SKU-A'])
    await wrapper.find('.osw-r-head .osw-link').trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })

  it('中间态非法（空值经 v-model 变 NaN）显示 is-invalid 样式', async () => {
    const wrapper = mountPanel([cartProduct({ processes: [procRow({ qty: 30 })] })])
    // 直改模型模拟非法中间态（如用户清空后 v-model 写入 NaN）
    const vm = wrapper.findComponent(OutsourceShipCartPanel)
    const groups = vm.props('groups') as CartProduct[]
    groups[0]!.processes[0]!.input.qty = Number.NaN
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.osw-qty').classes()).toContain('is-invalid')
  })
})

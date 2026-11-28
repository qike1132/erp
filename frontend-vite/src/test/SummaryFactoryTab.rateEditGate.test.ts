/**
 * 布料行「损耗率」输入可编辑门槛 + 保存反馈回归（2026-11-28 生产事故）。
 *
 * 事故：legacy 回退模式下无落库明细（item_ids=[]）的行照样渲染可编辑输入框，
 * 但 composable 保存时按空 item_ids 静默 return——展示值更新、零写入、零提示，
 * 用户以为存上了，刷新后回到旧值。修复：无明细行显示「—」（与按 SKU 模式
 * 既有只读语义一致），且 composable 兜底 toast。
 *
 * 本文件守两件事：
 *  1. 有 item_ids 的行 → 输入框照常渲染（零回归）；无 item_ids 的行 → 「—」不可编辑；
 *  2. lossRateSaveState='saved' 时渲染「已保存」反馈（同值保存零反馈曾引发用户反复重输）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SummaryFactoryTab from '@/views/purchase/components/SummaryFactoryTab.vue'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

/** legacy 回退模式（无 skus）：一行有明细、一行无明细。 */
function factoryData(): FactorySummaryData {
  return {
    success: true,
    order_count: 1,
    groups: [{
      customer_name: '客户甲',
      product_name: '产品',
      product_quantity: 100,
      suppliers: [{
        supplier_name: '供应商甲',
        fabrics: [
          { fabric_name: '宝乐绒', specification: 'S1', quantity: 50, unit: '米', item_ids: [1], loss_rate: 30 },
          { fabric_name: '新加布', specification: 'S2', quantity: 10, unit: '米' },
        ],
      }],
    }],
  }
}

function mountTab(props: Partial<{ lossRate: number; lossRateSaveState: 'idle' | 'saving' | 'saved' | 'error' }> = {}) {
  return mount(SummaryFactoryTab, {
    props: {
      factoryData: factoryData(),
      lossRate: props.lossRate ?? 5,
      orderCount: 1,
      lossRateSaveState: props.lossRateSaveState ?? 'idle',
      // 行率展示值来自 openSummary 播种的 fabricLossRates（[gi][si][fi]），
      // 缺省时组件回退 lossRate——此处按真实形状传入以断言行值。
      fabricLossRates: [[[30, 5]]],
    },
  })
}

describe('布料行损耗率输入门槛（item_ids 缺失 → 只读）', () => {
  it('有 item_ids 的行渲染可编辑输入框（零回归）', () => {
    const w = mountTab()
    const rows = w.findAll('tbody input[type="number"]')
    expect(rows).toHaveLength(1)
    expect((rows[0]!.element as HTMLInputElement).value).toBe('30')
    w.unmount()
  })

  it('无 item_ids 的行显示「—」并说明原因，绝不渲染输入框（静默不落库的入口被关死）', () => {
    const w = mountTab()
    const cells = w.findAll('tbody td')
    const placeholder = cells.find((c) => c.text() === '—')
    expect(placeholder).toBeDefined()
    // title 挂在内层说明 span 上
    expect(placeholder!.find('span[title]').attributes('title')).toContain('无法在此修改')
    // 全表体只有有明细那一行的输入框
    expect(w.findAll('tbody input[type="number"]')).toHaveLength(1)
    w.unmount()
  })
})

describe('损耗率保存反馈', () => {
  it("lossRateSaveState='saved' 渲染「已保存」（同值保存零反馈曾引发用户反复重输）", () => {
    const w = mountTab({ lossRateSaveState: 'saved' })
    expect(w.find('.sm-loss-hint').text()).toContain('已保存')
    w.unmount()
  })

  it("saving/error/mixed 的既有文案不变", () => {
    const saving = mountTab({ lossRateSaveState: 'saving' })
    expect(saving.find('.sm-loss-hint').text()).toContain('保存中…')
    saving.unmount()

    const error = mountTab({ lossRateSaveState: 'error' })
    expect(error.find('.sm-loss-hint').text()).toContain('保存失败')
    error.unmount()
  })
})

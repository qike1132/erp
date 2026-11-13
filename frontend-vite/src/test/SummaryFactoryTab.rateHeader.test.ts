/**
 * 「统一损耗率」输入框并入「损耗率」表头（2026-11-13 用户要求）的回归。
 *
 * 用户口径原文：把顶部「统一损耗率（千分之几）」的输入框合并进「损耗率」表头单元格，
 * 使输入框与表头融为一体；字体/字号/颜色/间距/边框/对齐与现有表头及其他单元格一致，
 * 多分辨率不错位不溢出，聚焦与编辑交互正常，且不影响其他列与原有功能。
 *
 * 本文件守三件事（都是「搬位置」最容易静默破掉的）：
 *  1. 输入框**在 thead 的「损耗率」th 里**，且工具栏不再有输入框 —— 位置即验收标准；
 *  2. 它仍是全表**第一个** number 输入（既有用例按 `inputs[0]` 取统一率，顺序不得变）；
 *  3. 归一化口径不变：>1000 夹到 1000、非法/负值归 0，且不随滚动误改。
 *
 * 提示位（.sm-loss-hint）绝对定位在概览行，契约由
 * QaSerializationStateMachine.adversarial.test.ts / useSummaryModal.lossRateHardening.test.ts 守。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SummaryFactoryTab from '@/views/purchase/components/SummaryFactoryTab.vue'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

/** 最小可渲染数据：单组单供应商单布料（回退模式，行模型最省字段）。 */
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
        fabrics: [{
          fabric_name: '宝乐绒', specification: 'S1', unit: '米',
          quantity: 50, item_ids: [1], loss_rate: 30,
        }],
      }],
    }],
  }
}

function mountTab(lossRate = 5) {
  return mount(SummaryFactoryTab, {
    props: { factoryData: factoryData(), lossRate, orderCount: 1 },
  })
}

describe('统一损耗率输入并入「损耗率」表头', () => {
  it('输入框渲染在 thead 的 .sm-rate-head 里，且工具栏不再有输入框', () => {
    const w = mountTab()
    const th = w.find('thead th.sm-rate-head')
    expect(th.exists()).toBe(true)
    expect(th.text()).toContain('损耗率')
    expect(th.find('input[type="number"]').exists()).toBe(true)

    // 正反两面：旧位置（概览行）必须干净，否则「合并」只做了一半，
    // 会出现两个能改同一份率的输入框（用户无从判断哪个生效）。
    expect(w.find('.smf-toolbar input').exists()).toBe(false)
    // 表头里只有这一个 number 输入；表体那颗是逐行材料率（语义不同，必须各归各处）
    expect(w.findAll('thead input[type="number"]')).toHaveLength(1)
    expect(w.findAll('tbody input[type="number"]')).toHaveLength(1)
    w.unmount()
  })

  it('仍是全表第一个 number 输入（既有用例的 inputs[0] 口径），并显示传入的率', () => {
    const w = mountTab(7)
    const first = w.findAll('input[type="number"]')[0]!
    expect(first.element).toBe(w.find('thead th.sm-rate-head input').element)
    expect((first.element as HTMLInputElement).value).toBe('7')
    w.unmount()
  })

  it('值与归一化口径不变：>1000 夹到 1000，负数/非法归 0', async () => {
    const w = mountTab(5)
    const input = w.find('thead th.sm-rate-head input[type="number"]')

    await input.setValue('1500')
    expect(w.emitted('lossRateInput')!.at(-1)).toEqual([1000])

    await input.setValue('-3')
    expect(w.emitted('lossRateInput')!.at(-1)).toEqual([0])

    await input.setValue('')
    expect(w.emitted('lossRateInput')!.at(-1)).toEqual([0])
    w.unmount()
  })

  it('表头格带说明语义：aria-label 含单位「千分之几」，并保留「统一」与「‰」标记', () => {
    const w = mountTab()
    const th = w.find('thead th.sm-rate-head')
    const input = th.find('input[type="number"]')

    expect(input.attributes('aria-label')).toContain('统一损耗率')
    expect(input.attributes('aria-label')).toContain('千分之几')
    // 表头主文案之外的两个量纲说明：缺了它们，用户会把订单级率当成本行材料率
    expect(th.find('.sm-rate-head__cap').text()).toBe('统一')
    expect(th.find('.sm-rate-head__unit').text()).toBe('‰')
    w.unmount()
  })

  it('提示位仍在概览行（不随输入框搬进表头）', () => {
    const w = mountTab()
    expect(w.find('.smf-toolbar .sm-loss-hint').exists()).toBe(true)
    expect(w.find('thead .sm-loss-hint').exists()).toBe(false)
    w.unmount()
  })

  /**
   * 表头格处在滚动区顶部，玩家滚轮命中概率远高于表体行；number 输入获焦时浏览器会把
   * 滚轮转成步进 → 滚动即静默改率并自动落库。故获焦态滚轮必须先失焦（改回滚动）。
   */
  it('获焦时滚轮不会改值：先失焦，滚轮交还表格', async () => {
    const w = mount(SummaryFactoryTab, {
      props: { factoryData: factoryData(), lossRate: 5, orderCount: 1 },
      attachTo: document.body,
    })
    const input = w.find('thead input[type="number"]')
    ;(input.element as HTMLInputElement).focus()
    expect(document.activeElement).toBe(input.element)

    await input.trigger('wheel')
    expect(document.activeElement).not.toBe(input.element)
    expect((input.element as HTMLInputElement).value).toBe('5')
    w.unmount()
  })
})

/**
 * OcrPreviewModal 渲染契约。
 *
 * 三种匹配态必须在视觉上可区分——用户是靠它们决定要不要改的：
 *   已匹配（精确）/ 模糊匹配（给置信度 + 露原图识别）/ 未匹配（必须手选）
 * 以及识别 0 条时的指引态必须给出路，而不是一句「失败」。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import OcrPreviewModal from '@/components/ocr/OcrPreviewModal.vue'
import type { OcrDraftItem } from '@/components/ocr/types'

const row = (over: Partial<OcrDraftItem> = {}): OcrDraftItem => ({
  uid: over.uid ?? 'u1',
  raw_product_name: '儿童保温杯500ml',
  product_id: 7,
  product_name: '儿童保温杯 500ml',
  match_confidence: 1,
  quantity: 50,
  unit: '箱',
  customer: '华东商贸',
  customer_id: 3,
  customer_confidence: 1,
  note: '',
  ...over,
})

function mountModal(draftItems: OcrDraftItem[], extra: Record<string, unknown> = {}) {
  const unmatched = draftItems.filter((i) => !i.product_id).length
  const badQty = draftItems.filter((i) => !(Number(i.quantity) >= 1)).length
  return mount(OcrPreviewModal, {
    global: {
      // UiDialog 基于 reka-ui，内容经 portal 渲染到 body；本仓库的既有做法是直接
      // stub 成普通容器（见 OutsourceShipDialog.test.ts），这样才能用 wrapper 断言。
      stubs: {
        UiDialog: {
          props: ['title', 'open'],
          template: '<div class="ui-dialog"><slot /><slot name="footer" /></div>',
        },
        UiButton: {
          props: ['variant', 'disabled', 'size'],
          emits: ['click'],
          template: '<button type="button" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
        UiAutocomplete: { template: '<div class="stub-ac" />' },
        FontAwesomeIcon: { template: '<i />' },
      },
    },
    props: {
      open: true,
      draftItems,
      showGuide: false,
      unmatchedCount: unmatched,
      invalidQuantityCount: badQty,
      missingCustomerCount: 0,
      warnings: [],
      rawText: '儿童保温杯500ml50箱',
      sourceName: 'shot.png',
      defaultCustomer: '华东商贸',
      searchProducts: vi.fn(async () => []),
      ...extra,
    },
  })
}

describe('OcrPreviewModal — 匹配态', () => {
  it('精确命中显示「精确」标记，不显示置信度', () => {
    const w = mountModal([row()])
    expect(w.find('.pill-ok').text()).toContain('精确')
    expect(w.find('.pill-mid').exists()).toBe(false)
  })

  it('模糊匹配显示置信度，并把原图识别露出来供人工核对', () => {
    const w = mountModal([
      row({ raw_product_name: '卡通雨伞8 骨', product_name: '卡通雨伞 8骨', match_confidence: 0.82 }),
    ])
    expect(w.find('.pill-mid').text()).toContain('82%')
    expect(w.find('.orig').text()).toContain('卡通雨伞8 骨')
  })

  it('未匹配渲染产品搜索框并要求手选，附原图识别提示', () => {
    const w = mountModal([
      row({ product_id: null, product_name: '儿童水壶600ml', raw_product_name: '儿童水壶600ml', match_confidence: 0 }),
    ])
    expect(w.find('.stub-ac').exists()).toBe(true)
    expect(w.find('.pick-hint').text()).toContain('儿童水壶600ml')
  })
})

describe('OcrPreviewModal — 汇总与确认', () => {
  it('汇总条区分已匹配与未匹配', () => {
    const w = mountModal([row(), row({ uid: 'u2', product_id: null })])
    expect(w.find('.ocr-sum .ok').text()).toContain('1')
    expect(w.find('.ocr-sum .bad').text()).toContain('1')
  })

  it('存在未匹配时确认按钮禁用，并说明原因', () => {
    const w = mountModal([row(), row({ uid: 'u2', product_id: null })])
    const confirm = w.findAll('button').find((b) => b.text().includes('导入暂存区'))!
    expect(confirm.attributes('disabled')).toBeDefined()
    expect(w.find('.foot-note').text()).toContain('未匹配')
  })

  it('全部匹配时确认按钮可用，点击抛 confirm', async () => {
    const w = mountModal([row()])
    const confirm = w.findAll('button').find((b) => b.text().includes('导入暂存区'))!
    expect(confirm.attributes('disabled')).toBeUndefined()
    await confirm.trigger('click')
    expect(w.emitted('confirm')).toBeTruthy()
  })

  it('删除某行后该行消失', async () => {
    const w = mountModal([row(), row({ uid: 'u2', product_name: '与伞' })])
    expect(w.findAll('.ocr-table tbody tr')).toHaveLength(2)
    await w.findAll('.del')[0]!.trigger('click')
    // 组件通过 v-model 抛新数组，父级数组不在此处被就地修改
    expect(w.emitted('update:draftItems')?.[0]?.[0]).toHaveLength(1)
    expect(w.findAll('.ocr-table tbody tr')).toHaveLength(1)
  })

  it('客户来自表单时打「取自表单」标记', () => {
    const w = mountModal([row({ customer: '华东商贸' })])
    expect(w.find('.src-tag').exists()).toBe(true)
  })
})

describe('OcrPreviewModal — 指引态', () => {
  it('识别 0 条时给出三条出路与识别原文', () => {
    const w = mountModal([], { showGuide: true, rawText: '王姐，这周要补一批货' })
    const text = w.text()
    expect(text).toContain('换一张更清晰的')
    expect(text).toContain('改用 Excel 导入')
    expect(text).toContain('手工录入这一条')
    expect(w.find('.raw-text').text()).toContain('王姐')
  })

  it('三条出路各自抛出对应事件', async () => {
    const w = mountModal([], { showGuide: true, rawText: 'x' })
    const btn = (label: string) => w.findAll('button').find((b) => b.text().includes(label))!
    await btn('重新粘贴').trigger('click')
    await btn('下载模板').trigger('click')
    await btn('去录入').trigger('click')
    expect(w.emitted('retry')).toBeTruthy()
    expect(w.emitted('download-template')).toBeTruthy()
    expect(w.emitted('go-manual')).toBeTruthy()
  })
})

describe('OcrPreviewModal — 审核修复', () => {
  it('删空所有行后仍显示确认表，不会变成"识别失败"指引态', () => {
    // 回归：指引态曾由 draftItems.length 派生，用户自己删光行会被报成识别失败
    const w = mountModal([])
    expect(w.find('.guide').exists()).toBe(false)
    expect(w.find('.ocr-empty').text()).toContain('已把识别到的条目全部移除')
    // 空表时不可导入
    const confirm = w.findAll('button').find((b) => b.text().includes('导入暂存区'))!
    expect(confirm.attributes('disabled')).toBeDefined()
  })

  it('数量非法时禁用导入并说明原因', () => {
    const w = mountModal([row({ quantity: 0 })], { invalidQuantityCount: 1 })
    const confirm = w.findAll('button').find((b) => b.text().includes('导入暂存区'))!
    expect(confirm.attributes('disabled')).toBeDefined()
    expect(w.find('.foot-note').text()).toContain('数量')
  })

  it('缺客户时禁用导入并说明原因', () => {
    const w = mountModal([row({ customer: '' })], { missingCustomerCount: 1 })
    const confirm = w.findAll('button').find((b) => b.text().includes('导入暂存区'))!
    expect(confirm.attributes('disabled')).toBeDefined()
    expect(w.find('.foot-note').text()).toContain('客户')
  })

  it('阻塞原因按优先级显示：未匹配 > 数量 > 客户', () => {
    const w = mountModal([row({ product_id: null })], {
      unmatchedCount: 1,
      invalidQuantityCount: 1,
      missingCustomerCount: 1,
    })
    expect(w.find('.foot-note').text()).toContain('未匹配')
  })

  it('后端 warnings 必须渲染出来，不能只存在状态里', () => {
    const w = mountModal([row()], {
      warnings: ['图上没有客户信息，已按当前选择的客户填入', '1 项产品在库内没有匹配，需要手动选择'],
    })
    const warn = w.find('.ocr-warn')
    expect(warn.exists()).toBe(true)
    expect(warn.text()).toContain('已按当前选择的客户填入')
    expect(warn.text()).toContain('没有匹配')
  })

  it('无 warnings 时不渲染提示块', () => {
    expect(mountModal([row()]).find('.ocr-warn').exists()).toBe(false)
  })
})

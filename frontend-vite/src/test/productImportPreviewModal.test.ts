/**
 * ProductImportPreviewModal 渲染契约。
 *
 * 用户是靠这张表决定「要不要真的导入」的，所以三件事必须在视觉上可区分：
 *   新增 / 补全（带改前改后）/ 跳过 / 错误，以及**客户未匹配要显眼**——
 *   「导入后没有客户和价格」正是从这一列看不出来导致的。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProductImportPreviewModal from '@/views/product/components/ProductImportPreviewModal.vue'
import type { ProductImportPreviewResult, ProductImportPreviewRow } from '@/types/api'

const row = (over: Partial<ProductImportPreviewRow> = {}): ProductImportPreviewRow => ({
  row_no: 2,
  action: 'create',
  name: '小熊抱枕 A款',
  barcode: '',
  price: '12.50',
  price_raw: '12.5',
  factory: '东莞',
  customer_name: '顺发玩具',
  customer_matched: true,
  has_image: false,
  changes: [],
  messages: [],
  ...over,
})

function makeResult(rows: ProductImportPreviewRow[]): ProductImportPreviewResult {
  const count = (a: string) => rows.filter((r) => r.action === a).length
  return {
    success: count('create') + count('backfill') > 0,
    message: '',
    filename: '新品录入.xlsx',
    row_count: rows.length,
    summary: { create: count('create'), backfill: count('backfill'), skip: count('skip'), error: count('error') },
    rows,
  }
}

function mountModal(result: ProductImportPreviewResult, importing = false) {
  return mount(ProductImportPreviewModal, {
    global: {
      // UiDialog 基于 reka-ui，内容经 portal 渲染到 body；本仓库既有做法是 stub 成普通容器
      // （见 OcrPreviewModal.test），这样才能用 wrapper 断言。
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
        FontAwesomeIcon: { template: '<i />' },
      },
    },
    props: { open: true, result, importing },
  })
}

describe('ProductImportPreviewModal', () => {
  it('汇总计数与逐行动作都渲染出来', () => {
    const result = makeResult([
      row({ row_no: 2, action: 'create' }),
      row({ row_no: 3, action: 'backfill', changes: ['价格 0.00 → 15.00'] }),
      row({ row_no: 4, action: 'skip', changes: [] }),
      row({ row_no: 5, action: 'error', name: '', changes: [], messages: ['缺少产品名称，本行无法导入'] }),
    ])
    const wrapper = mountModal(result)

    expect(wrapper.findAll('.chip-new').at(0)!.text()).toContain('1')
    expect(wrapper.findAll('.pill-create')).toHaveLength(1)
    expect(wrapper.findAll('.pill-backfill')).toHaveLength(1)
    expect(wrapper.findAll('.pill-skip')).toHaveLength(1)
    expect(wrapper.findAll('.pill-error')).toHaveLength(1)
    // 补全行必须给出「改前改后」
    expect(wrapper.text()).toContain('价格 0.00 → 15.00')
  })

  it('客户未匹配标红，且提示条单独可见', () => {
    const result = makeResult([
      row({ customer_name: '查无此客户', customer_matched: false,
            messages: ["行2: 客户'查无此客户'不存在于客户主数据，未挂客户归属"] }),
    ])
    const wrapper = mountModal(result)

    expect(wrapper.find('.cust-missing').exists()).toBe(true)
    expect(wrapper.find('.pi-warn').text()).toContain('不存在于客户主数据')
  })

  it('没有可导入的行时「确认导入」禁用', () => {
    const result = makeResult([
      row({ action: 'skip' }),
      row({ row_no: 3, action: 'error', name: '' }),
    ])
    const wrapper = mountModal(result)

    const confirm = wrapper.findAll('button').find((b) => b.text().includes('确认导入'))
    expect(confirm).toBeTruthy()
    expect(confirm!.attributes('disabled')).toBeDefined()
    expect(wrapper.find('.pi-foot-note').text()).toContain('没有可导入的行')
  })

  it('有可导入行时点「确认导入」抛出 confirm 事件', async () => {
    const wrapper = mountModal(makeResult([row({ action: 'create' })]))

    const confirm = wrapper.findAll('button').find((b) => b.text().includes('确认导入'))
    await confirm!.trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('导入中：按钮转「导入中…」并禁用，防重复提交', () => {
    const wrapper = mountModal(makeResult([row({ action: 'create' })]), true)

    const confirm = wrapper.findAll('button').find((b) => b.text().includes('导入中'))
    expect(confirm).toBeTruthy()
    expect(confirm!.attributes('disabled')).toBeDefined()
  })
})

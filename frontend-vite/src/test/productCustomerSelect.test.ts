/**
 * ProductCustomerSelect —— 产品「所属客户」多选控件
 *
 * 现有 UiSelect 是单选，产品归属是多对多，故单独做一个：已选项以 chips 展示，
 * 展开后是带搜索框的复选列表。
 *
 * 锁的行为：
 *   1. 勾选/取消都 emit 完整的新 id 数组（v-model 语义）；
 *   2. 未选任何客户时显示占位文案 —— 语义是「所有客户可见」，不是「谁都看不到」；
 *   3. 已选但不在选项里的客户 id 不能丢：保存时会把归属写空（等于放开给所有客户），
 *      这是静默的数据丢失，必须显示出来让用户看得见。
 */
import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ProductCustomerSelect from '@/views/product/components/ProductCustomerSelect.vue'

const OPTIONS = [
  { id: 1, name: '贝乐' },
  { id: 2, name: '海豚国际' },
  { id: 3, name: '星辉玩具' },
]

function mountSelect(modelValue: number[] = []) {
  return mount(ProductCustomerSelect, {
    props: { modelValue, options: OPTIONS, 'onUpdate:modelValue': () => {} },
    global: {
      // 面板经 Teleport 渲染到 body。stub 成就地渲染才能继续用 wrapper 断言
      // （与 ocrPreviewModal.test.ts / recordEditDialog.submit.test.ts 的既有做法一致）。
      // 面板为什么必须 teleport 出去，见下面那条回归用例。
      stubs: { teleport: true },
    },
  })
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ProductCustomerSelect', () => {
  it('勾选一个客户时 emit 包含它的新数组', async () => {
    const wrapper = mountSelect([])
    await wrapper.find('.pcs-field').trigger('click')
    await wrapper.findAll('.pcs-option')[0]!.trigger('click')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([[1]])
  })

  it('取消勾选时 emit 去掉它的新数组', async () => {
    const wrapper = mountSelect([1, 2])
    await wrapper.find('.pcs-field').trigger('click')
    await wrapper.findAll('.pcs-option')[1]!.trigger('click')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([[1]])
  })

  it('默认选完不收起，可连续勾选多个客户', async () => {
    const wrapper = mountSelect([])
    await wrapper.find('.pcs-field').trigger('click')
    await wrapper.findAll('.pcs-option')[0]!.trigger('click')

    expect(wrapper.find('.pcs-panel').exists()).toBe(true)
  })

  it('closeOnSelect 时勾一个客户就收起面板，多选靠再次点开', async () => {
    const wrapper = mount(ProductCustomerSelect, {
      props: { modelValue: [], options: OPTIONS, closeOnSelect: true, 'onUpdate:modelValue': () => {} },
      global: { stubs: { teleport: true } },
    })
    await wrapper.find('.pcs-field').trigger('click')
    expect(wrapper.find('.pcs-panel').exists()).toBe(true)

    await wrapper.findAll('.pcs-option')[0]!.trigger('click')

    expect(wrapper.find('.pcs-panel').exists()).toBe(false)
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([[1]])
  })

  it('未选客户时显示「所有客户可见」的占位，而不是空白', () => {
    const wrapper = mountSelect([])
    expect(wrapper.find('.pcs-placeholder').text()).toContain('所有客户')
  })

  it('已选客户的 chip 会显示出来', () => {
    const wrapper = mountSelect([1, 2])
    const chips = wrapper.findAll('.pcs-chip').map((c) => c.text())
    expect(chips[0]).toContain('贝乐')
    expect(chips[1]).toContain('海豚国际')
  })

  it('已选但已不在选项里的客户 id 仍要显示，不能被静默丢掉', () => {
    // 客户被停用/删除后，产品的历史归属会指向不在 activeNames 里的 id
    const wrapper = mountSelect([99])
    expect(wrapper.findAll('.pcs-chip')).toHaveLength(1)
    expect(wrapper.find('.pcs-chip').text()).toContain('99')
  })

  it('搜索框按名称过滤选项', async () => {
    const wrapper = mountSelect([])
    await wrapper.find('.pcs-field').trigger('click')
    await wrapper.find('.pcs-search').setValue('海豚')

    const names = wrapper.findAll('.pcs-option-name').map((n) => n.text())
    expect(names).toEqual(['海豚国际'])
  })

  it('面板必须 teleport 出组件子树，否则会被弹窗/左栏的 overflow 裁掉', async () => {
    // 弹窗内容区是 overflow-y:auto，左栏 .pd-col 是 overflow:hidden。
    // 面板留在子树里做 absolute 定位会被裁掉半截（2026-10-09 用户截图：
    // 客户下拉被弹窗底部切掉）。这条钉住「面板必须挂在 body 下」。
    const wrapper = mount(ProductCustomerSelect, {
      props: { modelValue: [], options: OPTIONS, 'onUpdate:modelValue': () => {} },
    })
    await wrapper.find('.pcs-field').trigger('click')

    expect(wrapper.element.querySelector('.pcs-panel')).toBeNull()
    expect(document.body.querySelector('.pcs-panel')).not.toBeNull()
  })

  /** 造一个字段矩形；jsdom 不做布局，getBoundingClientRect 必须自己喂 */
  function stubFieldRect(wrapper: ReturnType<typeof mountSelect>, rect: Partial<DOMRect>) {
    const el = wrapper.find('.pcs-field').element as HTMLElement
    const full = { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, ...rect }
    el.getBoundingClientRect = () => full as DOMRect
  }

  function setViewportHeight(h: number) {
    Object.defineProperty(window, 'innerHeight', { value: h, writable: true, configurable: true })
  }

  it('下方空间充足时贴在字段下沿，宽度与字段对齐', async () => {
    setViewportHeight(768)
    const wrapper = mount(ProductCustomerSelect, {
      props: { modelValue: [], options: OPTIONS, 'onUpdate:modelValue': () => {} },
    })
    stubFieldRect(wrapper, { top: 60, bottom: 100, left: 120, width: 300 })

    await wrapper.find('.pcs-field').trigger('click')

    const panel = document.body.querySelector<HTMLElement>('.pcs-panel')!
    expect(panel.style.top).toBe('106px') // bottom 100 + 6
    expect(panel.style.bottom).toBe('auto')
    expect(panel.style.left).toBe('120px')
    expect(panel.style.width).toBe('300px')
  })

  it('下方放不下时翻到字段上方，并把高度夹进可用空间', async () => {
    setViewportHeight(768)
    const wrapper = mount(ProductCustomerSelect, {
      props: { modelValue: [], options: OPTIONS, 'onUpdate:modelValue': () => {} },
    })
    // 字段贴着视口底部：下方只剩 22px，不足以放下最小高度
    stubFieldRect(wrapper, { top: 700, bottom: 740, left: 120, width: 300 })

    await wrapper.find('.pcs-field').trigger('click')

    const panel = document.body.querySelector<HTMLElement>('.pcs-panel')!
    expect(panel.style.top).toBe('auto')
    expect(panel.style.bottom).toBe('74px') // 768 - 700 + 6
    expect(panel.style.maxHeight).toBe('320px') // 上方有 694px，取面板上限
  })
})

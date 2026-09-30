/**
 * 明细筛选栏（RecordFilterBar）。
 *
 * 三个容易写错、错了又不容易看出来的点，各有一组断言：
 * 1. 关键词走「草稿 + 提交」——输入时不改筛选，只在 search/blur 时以 page:1 提交
 *    （实时绑定会让每敲一个字都发一次请求）。
 * 2. 已选中录单人时下拉**不消失**，且选项里始终有「全部录单人」可以清回全部。
 * 3. 各控件发出的筛选更新都带 page:1（否则从第 2 页缩小范围会得到空页）。
 *
 * 三个子控件全部 stub：本测试只验筛选栏自己发出的载荷，不验子控件渲染。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import RecordFilterBar from '@/views/production/components/RecordFilterBar.vue'
import { defaultRecordFilters, type RecordFilters } from '@/views/production/composables/recordFilters'

const stubs = {
  UiDateRangePicker: true,
  UiSelect: {
    name: 'UiSelect',
    props: ['modelValue', 'options', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<div class="ui-select-stub" />',
  },
  UiSearchInput: {
    name: 'UiSearchInput',
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue', 'search', 'blur'],
    template:
      '<input class="si" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @blur="$emit(\'blur\')" @keydown.enter="$emit(\'search\', modelValue)" />',
  },
}

function mountBar(overrides: Partial<RecordFilters> = {}, createdByOptions: Array<{ label: string; value: string }> = []) {
  return mount(RecordFilterBar, {
    props: {
      filters: { ...defaultRecordFilters(), ...overrides },
      departments: ['filling', 'handcraft', 'packaging'],
      createdByOptions,
    },
    global: { stubs },
  })
}

/** 录单人下拉：与部门下拉共用一个 UiSelect stub，靠 placeholder 区分 */
function createdBySelect(wrapper: ReturnType<typeof mountBar>) {
  return wrapper
    .findAllComponents({ name: 'UiSelect' })
    .find((c) => c.props('placeholder') === '全部录单人')
}

describe('RecordFilterBar', () => {
  it('输入关键词时不提交筛选（避免逐字发请求）', async () => {
    const wrapper = mountBar()

    await wrapper.find('input.si').setValue('白兔')

    expect(wrapper.emitted('update:filters')).toBeUndefined()
  })

  it('失焦时以 page:1 提交关键词', async () => {
    const wrapper = mountBar()

    await wrapper.find('input.si').setValue('白兔')
    await wrapper.find('input.si').trigger('blur')

    const emitted = wrapper.emitted('update:filters')
    expect(emitted).toHaveLength(1)
    expect(emitted![0]![0]).toMatchObject({ keyword: '白兔', page: 1 })
  })

  it('关键词未变化时失焦不发出多余的筛选更新', async () => {
    const wrapper = mountBar({ keyword: '白兔' })

    await wrapper.find('input.si').trigger('blur')

    expect(wrapper.emitted('update:filters')).toBeUndefined()
  })

  it('已选中录单人时下拉仍在，且选项含当前值与「全部录单人」', () => {
    // 本页记录里没有张三（createdByOptions 为空），但筛选值是张三：
    // 控件不能塌缩消失，否则筛选还在却退不出去。
    const wrapper = mountBar({ createdBy: '张三' }, [])
    const select = createdBySelect(wrapper)

    expect(select).toBeTruthy()
    const values = (select!.props('options') as Array<{ value: string }>).map((o) => o.value)
    expect(values).toContain('')
    expect(values).toContain('张三')
  })

  it('没有录单人可选且未选中时不渲染录单人下拉', () => {
    const wrapper = mountBar({}, [])

    expect(createdBySelect(wrapper)).toBeUndefined()
  })

  it('切换区间预设时带上 page:1', async () => {
    const wrapper = mountBar({ page: 3 })

    await wrapper.findAll('button')[0]!.trigger('click')

    const emitted = wrapper.emitted('update:filters')
    expect(emitted![0]![0]).toMatchObject({ page: 1 })
  })

  it('点击导出按钮 emit export', async () => {
    const wrapper = mountBar()

    await wrapper.find('[data-test="drawer-export"]').trigger('click')

    expect(wrapper.emitted('export')).toHaveLength(1)
  })
})

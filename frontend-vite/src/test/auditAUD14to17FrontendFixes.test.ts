/**
 * AUD-14~17 前端回归（2026-10-17 审计）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { formatQuantity } from '@/utils/quantity'
import FinishedStockRemarkCell from '@/views/finished-stock/FinishedStockRemarkCell.vue'

describe('AUD-14 数量格式化', () => {
  it('小数保留 ≤2 位、整数带千分位', () => {
    expect(formatQuantity(12.5)).toBe('12.5')
    expect(formatQuantity(0.4)).toBe('0.4')
    expect(formatQuantity(1234)).toBe('1,234')
    expect(formatQuantity('1.234')).toBe('1.23')
    expect(formatQuantity(null)).toBe('0')
  })

  it('来料详情不再对数量 toFixed(0)', () => {
    const src = readFileSync(
      resolve(__dirname, '../views/material/components/SupplierDialog.vue'),
      'utf-8',
    )
    expect(src).not.toMatch(/\.toFixed\(0\)/)
    expect(src).toMatch(/formatQuantity\(m\.ordered\)/)
  })
})

describe('AUD-15 超量提示不再被成功 toast 覆盖', () => {
  it('超量分支只发一条合并消息', () => {
    const src = readFileSync(
      resolve(__dirname, '../views/material/MaterialView.vue'),
      'utf-8',
    )
    expect(src).toMatch(/超出采购总量的/)
    // 旧写法：先 warning 再无条件 success（后者覆盖前者）
    expect(src).not.toMatch(/收货数量超过采购总量/)
  })
})

describe('AUD-16 虚拟列表 item-key 使用复合键', () => {
  it('与 rowKey 同口径（record_type:id）', () => {
    const src = readFileSync(
      resolve(__dirname, '../views/beile-order/BeileOrderTab.vue'),
      'utf-8',
    )
    expect(src).toMatch(/:item-key="\(i: BeileOrderRowType\) => `\$\{i\.record_type \?\? 'order'\}:\$\{i\.id\}`"/)
  })
})

describe('AUD-17 备注回车保存忽略 IME 组合态', () => {
  function mountCell() {
    return mount(FinishedStockRemarkCell, {
      props: { remark: '', editing: true, saving: false },
    })
  }

  it('组合期回车不触发保存', async () => {
    const wrapper = mountCell()
    const input = wrapper.find('input')
    await input.setValue('zhong')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })

    expect(wrapper.emitted('save')).toBeUndefined()
  })

  it('正常回车触发保存', async () => {
    const wrapper = mountCell()
    const input = wrapper.find('input')
    await input.setValue('备注')
    await input.trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('save')?.[0]).toEqual(['备注'])
  })
})

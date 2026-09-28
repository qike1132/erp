import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

/**
 * SupplierView 头部布局回归测试
 *
 * 背景：搜索框原先独占 `.sp-toolbar` 一行，与`.page-card-header`里的
 * 「添加供应商」按钮分成上下两行，头部因此占掉两条横栏的高度。
 * 现在搜索框移到卡片头部内、靠右，与按钮同行。
 */

vi.mock('@/api', () => ({
  supplierApi: {
    list: vi.fn().mockResolvedValue({ suppliers: [], total: 0 }),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    toggleStatus: vi.fn(),
  },
}))

import SupplierView from '@/views/supplier/SupplierView.vue'

function mountView() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SupplierView, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs: { SupplierTable: true, SupplierFormDialog: true, UiConfirmDialog: true },
    },
  })
}

describe('SupplierView 头部布局（搜索框与「添加供应商」同行）', () => {
  it('搜索框渲染在卡片头部内，排在添加按钮之后（靠右）', () => {
    const wrapper = mountView()
    const header = wrapper.find('.page-card-header')

    const addBtn = header.find('.sp-action-btn')
    const searchInput = header.find('input[type="text"]')
    expect(addBtn.exists()).toBe(true)
    expect(searchInput.exists()).toBe(true)

    // 按钮在搜索框之前；配合头部的 space-between，搜索框落在右上角
    const order = addBtn.element.compareDocumentPosition(searchInput.element)
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('搜索框不再独占一行（头部之下直接是表格）', () => {
    const wrapper = mountView()
    const card = wrapper.find('.page-card-main')

    expect(card.find('.sp-toolbar').exists()).toBe(false)
    // 头部之后紧跟表格，中间没有额外的工具条行
    expect(card.element.children[1]!.tagName.toLowerCase()).toContain('supplier-table')
  })
})

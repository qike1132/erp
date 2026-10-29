/**
 * 产品列表点图预览：必须用原图（image_original），而不是列表用的压缩图。
 *
 * 背景（2026-10-14）：存量图被 repoint 到压缩 .webp（product.image），预览弹窗此前
 * 直接加载 product.image → 展开看到的是压缩图。后端新增出站派生字段 image_original
 * （原始分辨率），本测试锁住「点缩略图 → open-image 事件带出 image_original」。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { VueQueryPlugin, QueryClient } from '@tanstack/vue-query'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'

const { getMock } = vi.hoisted(() => ({
  getMock: vi.fn(async () => ({
    items: [
      {
        id: 1,
        name: '小熊',
        barcode: '690',
        price: 9.9,
        image: '/static/uploads/x.webp',
        image_thumb: '/static/uploads/x.webp.thumb.webp',
        image_original: '/static/uploads/x.png',
        factory: '东莞',
        current_stock: 0,
        customers: [],
      },
    ],
    total: 1,
    page: 1,
    per_page: 20,
    pages: 1,
  })),
}))

vi.mock('@/api/request', () => ({
  get: getMock,
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  resolveStaticUrl: (u: string | null | undefined) => u ?? '',
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [],
    ensureActiveCustomerNames: vi.fn(async () => []),
  }),
}))

import ProductTable from '@/views/product/components/ProductTable.vue'

describe('产品列表点图预览', () => {
  it('点缩略图 → open-image 带出 image_original（原图），不是 image（压缩图）', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(ProductTable, {
      props: { actionId: null },
      global: {
        plugins: [
          [VueQueryPlugin, { queryClient: client }],
          [PrimeVue, { unstyled: true, pt: plushCutePT }],
        ],
        stubs: { UiSelect: true, FontAwesomeIcon: true },
      },
    })
    await new Promise((r) => setTimeout(r, 400)) // useEnhancedList 防抖 300ms
    await flushPromises()

    const box = wrapper.find('.pd-thumb-box')
    expect(box.exists()).toBe(true)
    await box.trigger('click')

    expect(wrapper.emitted('open-image')?.[0]).toEqual(['/static/uploads/x.png'])
  })

  it('缩略图 404 时立即回退原图；原图也失败才显示占位', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(ProductTable, {
      props: { actionId: null },
      global: {
        plugins: [
          [VueQueryPlugin, { queryClient: client }],
          [PrimeVue, { unstyled: true, pt: plushCutePT }],
        ],
        stubs: { UiSelect: true, FontAwesomeIcon: true },
      },
    })
    await new Promise((r) => setTimeout(r, 400))
    await flushPromises()

    let img = wrapper.find('.pd-thumb-img')
    expect(img.attributes('src')).toBe('/static/uploads/x.webp.thumb.webp')
    await img.trigger('error')
    await nextTick()
    img = wrapper.find('.pd-thumb-img')
    expect(img.attributes('src')).toBe('/static/uploads/x.webp')
    expect(wrapper.find('.pd-no-image').exists()).toBe(false)

    await img.trigger('error')
    await nextTick()
    expect(wrapper.find('.pd-no-image').exists()).toBe(true)
    wrapper.unmount()
  })
})

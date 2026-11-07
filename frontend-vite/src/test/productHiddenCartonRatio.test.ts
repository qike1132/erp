/**
 * 陈列样「隐藏款随箱配比」SKU 主数据字段 —— 新增表单与编辑弹窗的回归测试。
 *
 * 锁住三件事：
 *   1. 填写正整数（如 72）时随产品一起提交 hidden_carton_ratio；
 *   2. 留空 = 不启用（新增不传 / 编辑显式 null 清空），绝不能把「空」误当 0 提交；
 *   3. 非正整数（0 / 3.5）本地拦截并提示，不发起请求。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

type ProductPayload = {
  hidden_carton_ratio?: number | null
  [key: string]: unknown
}

const { createMock, updateMock, toastMock } = vi.hoisted(() => ({
  createMock: vi.fn(async (_payload: ProductPayload) => ({})),
  updateMock: vi.fn(async (_id: number, _payload: ProductPayload) => ({})),
  toastMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  productApi: { create: createMock, update: updateMock },
}))

vi.mock('@/api/request', () => ({
  resolveStaticUrl: (u: string | null | undefined) => u ?? '',
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [],
    ensureActiveCustomerNames: vi.fn(async () => []),
  }),
}))

vi.mock('@/views/product/composables/useImageUpload', () => ({
  uploadImage: vi.fn(),
  ALLOWED_IMAGE_HINT: '图片',
}))

vi.mock('@/composables/useImagePaste', () => ({
  useImagePaste: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: toastMock,
}))

vi.mock('@/types/errors', () => ({
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

import ProductBasicForm from '@/views/product/components/ProductBasicForm.vue'
import ProductEditDialog from '@/views/product/components/ProductEditDialog.vue'

function plugins() {
  return [[VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }]] as never
}

function stubs() {
  return {
    FontAwesomeIcon: true,
    ProductCustomerSelect: true,
    // 弹窗外壳只关心插槽内容，直通渲染即可
    UiDialog: { template: '<div class="dlg-stub"><slot name="title" /><slot /><slot name="footer" /></div>' },
  } as never
}

function mountBasicForm() {
  return mount(ProductBasicForm, {
    props: { factoryOptions: ['东莞', '湖北'] },
    global: { plugins: plugins(), stubs: stubs() },
  })
}

function mountEditDialog() {
  return mount(ProductEditDialog, {
    props: { factoryOptions: ['东莞', '湖北'] },
    global: { plugins: plugins(), stubs: stubs() },
  })
}

beforeEach(() => {
  createMock.mockClear()
  updateMock.mockClear()
  toastMock.mockClear()
})

describe('ProductBasicForm · 隐藏款随箱配比', () => {
  it('填 72 时随新增产品提交 hidden_carton_ratio=72', async () => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="product-name"]').setValue('市集拾趣陈列样')
    await wrapper.find('input[name="hidden-carton-ratio"]').setValue('72')

    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(createMock.mock.calls[0]![0].hidden_carton_ratio).toBe(72)
    expect(toastMock).toHaveBeenCalledWith('添加成功', 'success')
  })

  it('留空时不提交该字段（undefined），不误传 0', async () => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="product-name"]').setValue('普通公仔')

    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(createMock.mock.calls[0]![0].hidden_carton_ratio).toBeUndefined()
  })

  it.each(['0', '-1', '3.5'])('填非法值 %s 本地拦截，不发请求', async (bad) => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="product-name"]').setValue('市集拾趣陈列样')
    await wrapper.find('input[name="hidden-carton-ratio"]').setValue(bad)

    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    expect(createMock).not.toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith('隐藏款随箱配比必须为正整数（不超过 1000000）', 'warning')
  })

  it('提交成功后配比输入复位为空', async () => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="product-name"]').setValue('市集拾趣陈列样')
    await wrapper.find('input[name="hidden-carton-ratio"]').setValue('72')
    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    expect((wrapper.find('input[name="hidden-carton-ratio"]').element as HTMLInputElement).value).toBe('')
  })
})

describe('ProductEditDialog · 隐藏款随箱配比', () => {
  it('回显已配置的 72；未修改时保存不提交该字段（避免旧值覆盖丢失更新）', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open({
      id: 1, name: '陈列样', barcode: '', price: 0, factory: '东莞', image: null,
      hidden_carton_ratio: 72, customers: [],
    })
    await flushPromises()

    const input = wrapper.find('input[name="edit-hidden-carton-ratio"]').element as HTMLInputElement
    expect(input.value).toBe('72')

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    expect(updateMock).toHaveBeenCalledTimes(1)
    expect(updateMock.mock.calls[0]![1].hidden_carton_ratio).toBeUndefined()
  })

  it('改成 100 时提交新值', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open({
      id: 1, name: '陈列样', barcode: '', price: 0, factory: '东莞', image: null,
      hidden_carton_ratio: 72, customers: [],
    })
    await flushPromises()
    await wrapper.find('input[name="edit-hidden-carton-ratio"]').setValue('100')

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    expect(updateMock.mock.calls[0]![1].hidden_carton_ratio).toBe(100)
  })

  it('原有配比被清空时保存显式提交 null（停用规则），而不是漏字段', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open({
      id: 1, name: '陈列样', barcode: '', price: 0, factory: '东莞', image: null,
      hidden_carton_ratio: 72, customers: [],
    })
    await flushPromises()
    await wrapper.find('input[name="edit-hidden-carton-ratio"]').setValue('')

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    expect(updateMock.mock.calls[0]![1].hidden_carton_ratio).toBeNull()
  })

  it('未配置过的产品未改配比时也不提交该字段（三态与后端 model_fields_set 对齐）', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open({
      id: 2, name: '普通公仔', barcode: '', price: 0, factory: '东莞', image: null,
      customers: [],
    })
    await flushPromises()

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    expect(updateMock.mock.calls[0]![1].hidden_carton_ratio).toBeUndefined()
  })

  it('非法值本地拦截不发请求', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open({
      id: 1, name: '陈列样', barcode: '', price: 0, factory: '东莞', image: null,
      hidden_carton_ratio: 72, customers: [],
    })
    await flushPromises()
    await wrapper.find('input[name="edit-hidden-carton-ratio"]').setValue('0')

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    expect(updateMock).not.toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith('隐藏款随箱配比必须为正整数（不超过 1000000）', 'warning')
  })
})

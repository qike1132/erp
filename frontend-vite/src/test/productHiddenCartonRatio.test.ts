/**
 * 盲盒配置（产品录入）回归测试：盲盒开关、是否有隐藏款、配比联动与提交。
 *
 * 契约：
 *   1. 未勾选「盲盒」时不展示隐藏款相关录入项，也不提交这些字段；
 *   2. 勾选「盲盒」后展开「该 SKU 有隐藏款」与「盲盒隐藏款装箱配比」；
 *   3. 取消「有隐藏款」时配比禁用并清空（无隐藏款的盲盒按角色数均分）；
 *   4. 配比只在「盲盒 + 有隐藏款」时提交；非法值本地拦截；
 *   5. 编辑弹窗只提交被改动过的配比（避免旧值覆盖别处刚改的配置）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

type ProductPayload = {
  hidden_carton_ratio?: number | null
  is_blind_box?: boolean
  has_hidden_role?: boolean
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

const ROW_BLIND = {
  id: 1, name: '陈列样盲盒', barcode: '', price: 0, factory: '东莞', image: null,
  hidden_carton_ratio: 72, is_blind_box: true, has_hidden_role: true, customers: [],
}

beforeEach(() => {
  createMock.mockClear()
  updateMock.mockClear()
  toastMock.mockClear()
})

describe('ProductBasicForm · 盲盒配置', () => {
  it('未勾选盲盒时不展示隐藏款录入项，也不提交相关字段', async () => {
    const wrapper = mountBasicForm()
    expect(wrapper.find('input[name="create-hidden-carton-ratio"]').exists()).toBe(false)
    expect(wrapper.find('input[name="create-has-hidden-role"]').exists()).toBe(false)

    await wrapper.find('input[name="product-name"]').setValue('普通公仔')
    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    const payload = createMock.mock.calls[0]![0]
    expect(payload.is_blind_box).toBe(false)
    expect(payload.has_hidden_role).toBe(false)
    expect(payload.hidden_carton_ratio).toBeUndefined()
  })

  it('勾选盲盒后展开「有隐藏款」与配比；填 72 提交三个字段', async () => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="product-name"]').setValue('陈列样盲盒')
    await wrapper.find('input[name="create-is-blind-box"]').setValue(true)
    await wrapper.find('input[name="create-has-hidden-role"]').setValue(true)
    await wrapper.find('input[name="create-hidden-carton-ratio"]').setValue('72')

    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    const payload = createMock.mock.calls[0]![0]
    expect(payload.is_blind_box).toBe(true)
    expect(payload.has_hidden_role).toBe(true)
    expect(payload.hidden_carton_ratio).toBe(72)
  })

  it('盲盒无隐藏款：配比禁用且提交 has_hidden_role=false、不带配比', async () => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="product-name"]').setValue('盲盒无隐藏')
    await wrapper.find('input[name="create-is-blind-box"]').setValue(true)

    const ratio = wrapper.find('input[name="create-hidden-carton-ratio"]')
    expect(ratio.attributes('disabled')).toBeDefined()

    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    const payload = createMock.mock.calls[0]![0]
    expect(payload.is_blind_box).toBe(true)
    expect(payload.has_hidden_role).toBe(false)
    expect(payload.hidden_carton_ratio).toBeUndefined()
  })

  it('取消「有隐藏款」会清空已填配比', async () => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="create-is-blind-box"]').setValue(true)
    await wrapper.find('input[name="create-has-hidden-role"]').setValue(true)
    await wrapper.find('input[name="create-hidden-carton-ratio"]').setValue('72')
    await wrapper.find('input[name="create-has-hidden-role"]').setValue(false)
    await flushPromises()

    const input = wrapper.find('input[name="create-hidden-carton-ratio"]').element as HTMLInputElement
    expect(input.value).toBe('')
    expect(input.disabled).toBe(true)
  })

  it.each(['0', '-1', '3.5'])('填非法值 %s 本地拦截，不发请求', async (bad) => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="product-name"]').setValue('陈列样盲盒')
    await wrapper.find('input[name="create-is-blind-box"]').setValue(true)
    await wrapper.find('input[name="create-has-hidden-role"]').setValue(true)
    await wrapper.find('input[name="create-hidden-carton-ratio"]').setValue(bad)

    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    expect(createMock).not.toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith('盲盒隐藏款装箱配比必须为正整数（不超过 1000000）', 'warning')
  })

  it('提交成功后盲盒配置复位', async () => {
    const wrapper = mountBasicForm()
    await wrapper.find('input[name="product-name"]').setValue('陈列样盲盒')
    await wrapper.find('input[name="create-is-blind-box"]').setValue(true)
    await wrapper.find('input[name="create-has-hidden-role"]').setValue(true)
    await wrapper.find('input[name="create-hidden-carton-ratio"]').setValue('72')
    await wrapper.find('button.pd-btn-primary').trigger('click')
    await flushPromises()

    expect((wrapper.find('input[name="create-is-blind-box"]').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find('input[name="create-hidden-carton-ratio"]').exists()).toBe(false)
  })
})

describe('ProductEditDialog · 盲盒配置', () => {
  it('回显盲盒与配比；未修改时保存不提交配比字段', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open(ROW_BLIND)
    await flushPromises()

    expect((wrapper.find('input[name="edit-is-blind-box"]').element as HTMLInputElement).checked).toBe(true)
    expect((wrapper.find('input[name="edit-has-hidden-role"]').element as HTMLInputElement).checked).toBe(true)
    const ratio = wrapper.find('input[name="edit-hidden-carton-ratio"]').element as HTMLInputElement
    expect(ratio.value).toBe('72')

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    const payload = updateMock.mock.calls[0]![1]
    expect(payload.is_blind_box).toBe(true)
    expect(payload.has_hidden_role).toBe(true)
    expect(payload.hidden_carton_ratio).toBeUndefined()
  })

  it('改成 100 时提交新配比', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open(ROW_BLIND)
    await flushPromises()
    await wrapper.find('input[name="edit-hidden-carton-ratio"]').setValue('100')

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    expect(updateMock.mock.calls[0]![1].hidden_carton_ratio).toBe(100)
  })

  it('清空配比保存时显式提交 null（不额外配隐藏款）', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open(ROW_BLIND)
    await flushPromises()
    await wrapper.find('input[name="edit-hidden-carton-ratio"]').setValue('')

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    expect(updateMock.mock.calls[0]![1].hidden_carton_ratio).toBeNull()
  })

  it('关闭「有隐藏款」后配比清空且按 null 提交', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open(ROW_BLIND)
    await flushPromises()
    await wrapper.find('input[name="edit-has-hidden-role"]').setValue(false)

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    const payload = updateMock.mock.calls[0]![1]
    expect(payload.has_hidden_role).toBe(false)
    expect(payload.hidden_carton_ratio).toBeNull()
  })

  it('非盲盒产品：不展示配比，保存提交 false/false 且不带配比', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open({
      id: 2, name: '普通公仔', barcode: '', price: 0, factory: '东莞', image: null,
      customers: [],
    })
    await flushPromises()

    expect(wrapper.find('input[name="edit-hidden-carton-ratio"]').exists()).toBe(false)

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    const payload = updateMock.mock.calls[0]![1]
    expect(payload.is_blind_box).toBe(false)
    expect(payload.has_hidden_role).toBe(false)
    expect(payload.hidden_carton_ratio).toBeUndefined()
  })

  it('非法值本地拦截不发请求', async () => {
    const wrapper = mountEditDialog()
    wrapper.vm.open(ROW_BLIND)
    await flushPromises()
    await wrapper.find('input[name="edit-hidden-carton-ratio"]').setValue('0')

    await wrapper.find('.bom-btn-save').trigger('click')
    await flushPromises()

    expect(updateMock).not.toHaveBeenCalled()
    expect(toastMock).toHaveBeenCalledWith('盲盒隐藏款装箱配比必须为正整数（不超过 1000000）', 'warning')
  })
})

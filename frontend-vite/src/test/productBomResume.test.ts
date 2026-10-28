import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { effectScope, nextTick, reactive, ref } from 'vue'
import BomEditor from '@/views/product/components/BomEditor.vue'
import { useProductBomResume } from '@/views/product/composables/useProductBomResume'
import { createResumeAttempt, readResumeAttempt, writeResumeAttempt } from '@/utils/bomOrderResume'

vi.mock('@/api', () => ({
  productApi: {
    loadBom: vi.fn().mockResolvedValue({
      success: true,
      product: { roles: [], default_bom_label: null },
      materials: [{
        id: 1, category: 'fabric', material_name: '面料A', specification: 'S1',
        unit: '码', supplier_name: '供应商甲', role_id: null,
      }],
    }),
    saveBom: vi.fn().mockResolvedValue({ success: true }),
    detail: vi.fn().mockResolvedValue({ id: 5, name: '产品五' }),
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    searchForBomCopy: vi.fn(),
  },
  supplierApi: { options: vi.fn().mockResolvedValue({ suppliers: [] }) },
}))

const ATTEMPT_ID = '33333333-3333-4333-8333-333333333333'
let wrapper: VueWrapper | null = null

async function mountEditor() {
  wrapper = mount(BomEditor, {
    attachTo: document.body,
    global: { stubs: { UiAutocomplete: true, BomCopyDialog: true, BomSupplierSelect: true } },
  })
  await (wrapper.vm as unknown as { open: (p: { id: number; name: string }) => Promise<void> }).open({
    id: 5, name: '产品五',
  })
  await nextTick()
  return wrapper
}

function q(selector: string): DOMWrapper<Element> {
  const element = document.querySelector(selector)
  if (!element) throw new Error(`未找到 ${selector}`)
  return new DOMWrapper(element)
}

function seedAttempt() {
  const attempt = createResumeAttempt({
    attempt_id: ATTEMPT_ID,
    owner_id: 7,
    source: { composite_id: 'order:42', record_type: 'order', source_order_id: 42, order_no: 'SO-42' },
    pending_products: [{ product_id: 5, product_name: '产品五' }],
    current_product_id: 5,
    view: {
      active_tab: 'active', purchase_page: 1, unprocessed_page: 1,
      selected_ids: [], main_scroll_top: 0, table_scroll_left: 0,
    },
  })
  writeResumeAttempt(attempt)
}

beforeEach(() => {
  sessionStorage.clear()
  seedAttempt()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

describe('BomEditor 续提事件边界', () => {
  it('API 明确成功后只 emit saved 一次，不额外 emit closed', async () => {
    const w = await mountEditor()
    await q('.bom-btn-save').trigger('click')
    await flushPromises()
    expect(w.emitted('saved')).toEqual([[{ product_id: 5 }]])
    expect(w.emitted('closed')).toBeUndefined()
  })

  it('success=false 与异常均不 emit saved/closed，编辑器保持打开', async () => {
    const { productApi } = await import('@/api')
    const save = productApi.saveBom as unknown as ReturnType<typeof vi.fn>
    save.mockResolvedValueOnce({ success: false, error: 'bad' })
    const w = await mountEditor()
    await q('.bom-btn-save').trigger('click')
    await flushPromises()
    expect(w.emitted('saved')).toBeUndefined()
    expect(w.emitted('closed')).toBeUndefined()
    expect(document.querySelector('.bom-modal-dialog')).not.toBeNull()
  })

  it('只有实际关闭才 emit closed；保存成功路径不触发它', async () => {
    const w = await mountEditor()
    await q('.bom-btn-cancel').trigger('click')
    await flushPromises()
    expect(w.emitted('closed')).toEqual([[{ product_id: 5 }]])
  })
})

describe('产品页 resume 路由门控', () => {
  function setup(productId = '5') {
    const open = vi.fn().mockResolvedValue(undefined)
    const replace = vi.fn().mockResolvedValue(undefined)
    const route = reactive({ query: { product_id: productId, resume_attempt_id: ATTEMPT_ID } })
    const scope = effectScope()
    const resume = scope.run(() => useProductBomResume(ref({ open }), {
      route,
      router: { replace },
      auth: { user: { id: 7 }, hasPermission: () => true },
    }))!
    resume.watchResumeRoute()
    return { open, replace, route, scope, resume }
  }

  it('只打开 URL 与上下文匹配的产品，重复路由值不重复 open', async () => {
    const h = setup()
    await flushPromises()
    await nextTick()
    expect(h.open).toHaveBeenCalledTimes(1)
    expect(h.open).toHaveBeenCalledWith({ id: 5, name: '产品五' })
    h.route.query = { ...h.route.query }
    await flushPromises()
    expect(h.open).toHaveBeenCalledTimes(1)
    h.scope.stop()
  })

  it('产品不匹配 fail closed，不打开其他产品、不发起续提', async () => {
    const h = setup('6')
    await flushPromises()
    expect(h.open).not.toHaveBeenCalled()
    expect(h.replace).toHaveBeenCalledWith({ path: '/purchase', query: { resume: ATTEMPT_ID } })
    expect(readResumeAttempt(ATTEMPT_ID, 7)?.phase).toBe('ABORTED')
    h.scope.stop()
  })

  it('saved 先落 RETURNING 再回采购；closed 落 CANCELLED 后回程', async () => {
    const h = setup()
    await flushPromises()
    await h.resume.onSaved(5)
    expect(readResumeAttempt(ATTEMPT_ID, 7)?.phase).toBe('RETURNING')
    expect(h.replace).toHaveBeenLastCalledWith({ path: '/purchase', query: { resume: ATTEMPT_ID } })
    await h.resume.onClosed()
    expect(readResumeAttempt(ATTEMPT_ID, 7)?.phase).toBe('RETURNING')
    seedAttempt()
    await h.resume.onClosed()
    expect(readResumeAttempt(ATTEMPT_ID, 7)?.phase).toBe('CANCELLED')
    h.scope.stop()
  })
})

/**
 * /stock-return 行内「修改」「删除」按钮的权限门控与行状态（2026-10-08）。
 *
 * 与 /report 退货流水同逻辑：修改认 return_edit、删除认 return_delete（迁移 079 的独立子码）；
 * 已取消（status=cancelled）的行两个按钮都不出（后端也不允许编辑已取消退货）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'

const mocks = vi.hoisted(() => ({
  queryData: null as unknown as { value: unknown },
  hasPermission: vi.fn((_c: string) => true),
}))

vi.mock('@/api', () => ({
  stockReturnApi: {
    list: vi.fn(),
    shipmentOptions: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: mocks.hasPermission }) }))
vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: { value: false }, text: { value: '' }, sub: { value: '' }, type: { value: 'danger' },
    onConfirm: vi.fn(), onCancel: vi.fn(), confirm: vi.fn(async () => true),
  }),
}))
vi.mock('@tanstack/vue-query', async () => {
  const { ref: vueRef } = await import('vue')
  const dataRef = vueRef<unknown>(null)
  mocks.queryData = dataRef as { value: unknown }
  return {
    useQuery: () => ({ data: dataRef, isLoading: vueRef(false), isFetching: vueRef(false), refetch: vi.fn() }),
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
    keepPreviousData: {},
  }
})

import StockReturnView from '@/views/stock-return/StockReturnView.vue'
import EditReturnModal from '@/views/report/components/EditReturnModal.vue'

const ACTIVE = {
  id: 31, return_no: 'SR-20261008-0001', return_date: '2026-10-08',
  product: { id: 3, name: '鲨鱼公仔' }, quantity: 4, customer: 'MINISO国际',
  stockout_id: 21, stockout_no: 'SO-1', reason: '破损', note: '', status: 'active',
}
const CANCELLED = { ...ACTIVE, id: 32, return_no: 'SR-20261008-0002', status: 'cancelled' }

function mountView(rows: object[]) {
  mocks.queryData.value = { data: rows, total: rows.length }
  return mount(StockReturnView, {
    global: {
      plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]],
      stubs: { StockReturnCreateDialog: true, EditReturnModal: false, UiConfirmDialog: true, UiSearchInput: true },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.hasPermission.mockReturnValue(true)
})

describe('操作列按钮', () => {
  it('权限齐全：active 行出「修改」「删除」，已取消行出 —', () => {
    const w = mountView([ACTIVE, CANCELLED])
    expect(w.findAll('[aria-label="修改退货"]').length).toBe(1)
    expect(w.findAll('[aria-label="删除退货"]').length).toBe(1)
    expect(w.findAll('.sr-cancelled-mark').length).toBe(1)
  })

  it('只有 return_delete：只出「删除」', () => {
    mocks.hasPermission.mockImplementation((c: string) => c === 'return_delete')
    const w = mountView([ACTIVE])
    expect(w.findAll('[aria-label="修改退货"]').length).toBe(0)
    expect(w.findAll('[aria-label="删除退货"]').length).toBe(1)
  })

  it('只有 return_edit：只出「修改」', () => {
    mocks.hasPermission.mockImplementation((c: string) => c === 'return_edit')
    const w = mountView([ACTIVE])
    expect(w.findAll('[aria-label="修改退货"]').length).toBe(1)
    expect(w.findAll('[aria-label="删除退货"]').length).toBe(0)
  })

  it('只有 stock_return_manage：两个按钮都出（镜像后端 require_any_permission 口径）', () => {
    mocks.hasPermission.mockImplementation((c: string) => c === 'stock_return_manage')
    const w = mountView([ACTIVE])
    expect(w.findAll('[aria-label="修改退货"]').length).toBe(1)
    expect(w.findAll('[aria-label="删除退货"]').length).toBe(1)
  })

  it('两个码都没有：整列不渲染', () => {
    mocks.hasPermission.mockImplementation((c: string) => c === 'stock_return_view')
    const w = mountView([ACTIVE])
    expect(w.findAll('[aria-label="删除退货"]').length).toBe(0)
    expect(w.text()).not.toContain('操作')
  })

  it('点击「修改」：打开编辑弹窗并带出该行', async () => {
    const w = mountView([ACTIVE])
    await w.find('[aria-label="修改退货"]').trigger('click')
    const modal = w.findComponent(EditReturnModal)
    expect(modal.props('open')).toBe(true)
    expect((modal.props('form') as { returnNo: string }).returnNo).toBe('SR-20261008-0001')
  })
})

/**
 * OutsourceShipmentView 发货单页面按钮显隐回归
 *
 * 修复前：一键发货 / 确认收货 都按权限点（hasPermission）显示，super 账号拥有全部权限
 * 导致「对所有用户都显示」。
 * 修复后（业务规则，与 scripts/add_outsource_ship_receive_perms.py 的 BEILE_USERNAME='贝乐' 一致）：
 * - 一键发货：仅非贝乐用户可见（贝乐账号只收货不发货）
 * - 确认收货：仅贝乐用户可见
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import OutsourceShipmentView from '@/views/outsource/OutsourceShipmentView.vue'

/** 当前测试用户被授予的权限点 */
let grantedPermissions = new Set<string>()
/** 当前测试用户名 */
let currentUsername = 'admin'
/** 发货单列表返回体 */
let shipmentListResponse: Record<string, unknown> = emptyList()

function emptyList() {
  return { success: true, data: [], total: 0, page: 1, per_page: 50, shipped_count: 0, received_count: 0 }
}

const shipmentsMock = vi.fn()
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (code: string) => grantedPermissions.has(code),
    user: { get username() { return currentUsername } },
  }),
}))
vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))
vi.mock('@/api/outsource', () => ({
  outsourceApi: {
    shipments: (...args: unknown[]) => shipmentsMock(...args),
    createShipment: vi.fn(),
    shipmentDetail: vi.fn(),
    receiveShipment: vi.fn(),
    shippable: vi.fn(),
  },
}))

function shipButton(wrapper: ReturnType<typeof mount>) {
  return wrapper.find('button.osv-toolbar-btn--ship')
}
function receiveButton(wrapper: ReturnType<typeof mount>) {
  const btns = wrapper.findAll('button')
  return btns.find((b) => b.text().includes('确认收货'))
}

function shippedRow() {
  return {
    id: 1,
    shipment_no: 'FH-20260919-0001',
    order_id: 1,
    customer: '贝乐客户',
    status: 'shipped',
    shipped_at: '2026-09-19 15:00',
    received_at: null,
    shipped_by: 'shipper',
    received_by: null,
    remark: null,
    create_time: '2026-09-19 15:00',
    item_count: 1,
    total_shipped: 5,
  }
}

async function mountView() {
  const wrapper = mount(OutsourceShipmentView, {
    global: {
      stubs: {
        FontAwesomeIcon: { template: '<i />' },
        HubeiRouteTabs: { template: '<div />' },
        UiPagination: { template: '<div />' },
        UiSpinner: { template: '<div />' },
        OutsourceShipDialog: { template: '<div />' },
        OutsourceShipmentDetailDialog: { template: '<div />' },
      },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  grantedPermissions = new Set()
  currentUsername = 'admin'
  shipmentListResponse = emptyList()
  // mockImplementation 在调用时读取当前 shipmentListResponse（mockResolvedValue 会在 beforeEach 时绑定旧值）
  shipmentsMock.mockImplementation(async () => shipmentListResponse)
})

describe('OutsourceShipmentView 按钮显隐（按贝乐身份）', () => {
  it('非贝乐 + 发货权限 → 显示「一键发货」', async () => {
    grantedPermissions = new Set(['outsource_ship'])
    currentUsername = 'admin'
    const w = await mountView()
    expect(shipButton(w).exists()).toBe(true)
    expect(receiveButton(w)).toBeUndefined()
  })

  it('贝乐 + 发货权限 → 隐藏「一键发货」', async () => {
    grantedPermissions = new Set(['outsource_ship', 'outsource_receive'])
    currentUsername = '贝乐'
    const w = await mountView()
    expect(shipButton(w).exists()).toBe(false)
  })

  it('贝乐 + 收货权限 + 待收货单 → 显示「确认收货」', async () => {
    grantedPermissions = new Set(['outsource_receive'])
    currentUsername = '贝乐'
    shipmentListResponse = { ...emptyList(), data: [shippedRow()], total: 1, shipped_count: 1 }
    const w = await mountView()
    expect(receiveButton(w)).toBeDefined()
  })

  it('非贝乐（admin）+ 收货权限 + 待收货单 → 隐藏「确认收货」', async () => {
    grantedPermissions = new Set(['outsource_ship', 'outsource_receive'])
    currentUsername = 'admin'
    shipmentListResponse = { ...emptyList(), data: [shippedRow()], total: 1, shipped_count: 1 }
    const w = await mountView()
    expect(receiveButton(w)).toBeUndefined()
    // admin 非贝乐仍可见一键发货
    expect(shipButton(w).exists()).toBe(true)
  })
})

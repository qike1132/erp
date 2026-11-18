/**
 * 出货录入「可出货量」契约回归（2026-10-17 审计 P1-16 / 报告内 P1-1）
 *
 * 缺陷：`/aux/available-shipment` 返回**扁平对象**
 * `{order_quantity, shipped_quantity, available_quantity}`（后端 `AvailableShipmentResponse`，
 * 无 `{success,data}` 信封），而 `src/api/stock.ts` 把它声明成 `ApiResponse<ShipmentInfo>`，
 * 两个消费点又各自拆了第二次 `.data` → 恒 `undefined`：
 *   1) `useStockOutAvailabilityGates.fetchAvailableShipment` 返回 null ⇒
 *      `checkProductAvailability` 走 `avail === undefined → return true`（fail-open）；
 *   2) `useStockOutActions` 的提交期预检 `const shipment = data.data` ⇒ 超额组永远收集不到；
 *   3) `StockOutTab.shipmentInfo` 恒 null ⇒ 录入页「可出货量」永久不显示。
 * 于是页面不报错、不 500，只是闸门安静失效，用户能把任意大数量加进暂存区，
 * 到提交时才被后端逐行拒（部分成功 + 重试 = 重复出库高发形态）。
 *
 * 本用例用**真实响应形状**驱动整条链路（request 层 mock，不 mock stockApi），
 * 把 api 声明改回 `ApiResponse<ShipmentInfo>` 或把 `.data` 拆回来都必须变红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: mocks.getMock,
  post: mocks.postMock,
  put: vi.fn(),
  del: vi.fn(),
  upload: vi.fn(),
  download: vi.fn(),
}))

vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [],
    ensureActiveCustomerNames: vi.fn(async () => {}),
  }),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: mocks.showToast,
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import StockOutTab from '@/views/stock/StockOutTab.vue'
import type { ShipmentInfo, StagedStockout } from '@/types'

/** 后端 `AvailableShipmentResponse` 的**真实**形状：扁平对象，无 data 包装 */
const SHIPMENT: ShipmentInfo = {
  order_quantity: 10,
  shipped_quantity: 0,
  available_quantity: 10,
}

function mountTab() {
  return mount(StockOutTab, {
    global: {
      stubs: {
        StockOutInputForm: true,
        StockOutStagingList: true,
        StockOutEditStagedDialog: true,
        UiConfirmDialog: true,
        UiButton: { template: '<button><slot /></button>' },
      },
    },
  })
}

interface StockOutTabVm {
  form: { customer: string; date: string; search: string; productId: string; quantity: number; note: string; batchNo: string }
  addStaged: () => Promise<void>
  staged: StagedStockout[]
  shipmentInfo: ShipmentInfo | null
  fetchShipmentInfo: () => Promise<void>
}

async function stageOne(vm: StockOutTabVm, quantity: number, customer = '客户A') {
  vm.form.productId = '7'
  vm.form.search = '产品A'
  vm.form.customer = customer
  vm.form.quantity = quantity
  vm.form.batchNo = ''
  // 刻意**不等** watch(customer) 触发的展示请求：闸门与展示各自独立序号（2026-10-17 审计
  // P1-16 评审 M2），展示请求在途不该影响闸门判定。若哪天又把两者并回一个序号池，
  // 这里会 fail-open 放行超额行，下面的用例立刻变红。
  await vm.addStaged()
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getMock.mockImplementation(async (url: string) => {
    if (url === '/aux/available-shipment') return { ...SHIPMENT }
    if (url === '/finished-stock/batches') return { success: true, data: [] }
    return { success: true, data: [] }
  })
})

describe('出货录入可出货量契约（P1-16）', () => {
  it('可出货量按扁平对象取出并展示（旧实现恒 null）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    vm.form.productId = '7'
    vm.form.customer = '客户A'

    await flushPromises() // 消化 watch(customer) 自动触发的同一次展示请求
    await vm.fetchShipmentInfo()

    expect(vm.shipmentInfo).toEqual(SHIPMENT)
    expect(vm.shipmentInfo?.available_quantity).toBe(10)
  })

  it('录入门禁：数量超过可出货量必须拒绝加入暂存区（旧实现恒放行）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm

    await stageOne(vm, 999)

    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('出货数量超过可出货量'), 'error')
    expect(vm.staged).toHaveLength(0)
  })

  it('录入门禁：未超可出货量照常暂存（防矫枉过正）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm

    await stageOne(vm, 4)

    expect(mocks.showToast).not.toHaveBeenCalledWith(expect.stringContaining('出货数量超过可出货量'), 'error')
    expect(vm.staged).toHaveLength(1)
  })

  it('录入门禁按产品累计：已暂存 6 件后再加 5 件必须拦（11 > 10）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm

    await stageOne(vm, 6)
    expect(vm.staged).toHaveLength(1)

    await stageOne(vm, 5)

    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('出货数量超过可出货量'), 'error')
    expect(vm.staged).toHaveLength(1)
  })

  it('双击「添加」：并发两次闸门请求都不得 fail-open（序号撞车曾放行超额行）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm

    vm.form.productId = '7'
    vm.form.search = '产品A'
    vm.form.customer = '客户A'
    vm.form.quantity = 999
    vm.form.batchNo = ''

    // 不 await 第一次：两次闸门请求同时在途（真机双击即此形态）
    await Promise.all([vm.addStaged(), vm.addStaged()])

    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('出货数量超过可出货量'), 'error')
    expect(vm.staged).toHaveLength(0)
  })
})

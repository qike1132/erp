/**
 * 皮套库存面板「导出」按钮的失败反馈（2026-11-16 上线前审计 Medium）。
 *
 * 缺陷：`void caseApi.exportXlsx(...)` —— 既无 catch 也无 loading，按钮也不禁用。
 * 导出失败（超上限 400 / 网络断 / 权限不足）时页面零反馈，用户只看到「点了没反应」，
 * 会反复点、反复失败；连点还会并发下载多份。
 *
 * 修复：改用 useExport（/stock 与 /finished-stock 的同一范式），失败走 toast.error，
 * 导出期间按钮 disabled 并显示「导出中…」。
 *
 * 断言口径：失败提示用的是 useExport 的 message 提取（getErrorMessage）——这里用
 * `new Error('导出超上限')` 触发，于是期望 toast.error 收到的正是那句用户能看懂的文案。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  exportXlsx: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api', () => ({
  caseApi: { exportXlsx: mocks.exportXlsx },
}))

vi.mock('@/composables/useToast', () => ({
  toast: {
    info: vi.fn(),
    success: vi.fn(),
    error: mocks.toastError,
    warning: vi.fn(),
  },
  showToast: vi.fn(),
}))

// 库存数据层整块替换：本用例只关心导出按钮，不关心库存查询链路（那是 useCaseInventory
// 自己的测试面），保持面板可挂载即可。
vi.mock('@/views/case/composables/useCaseInventory', () => ({
  useCaseInventory: () => ({
    invSearch: ref(''),
    invPage: ref(1),
    invPerPage: ref(50),
    invIsLoading: ref(false),
    invIsFetching: ref(false),
    invRefetch: vi.fn(),
    inventoryList: ref([]),
    invTotal: ref(0),
    invTotalPages: ref(0),
    invStats: ref(null),
    onInvSearchInput: vi.fn(),
    onInvPageChange: vi.fn(),
    openLogDrawer: vi.fn(),
    selectedCase: ref(null),
    drawerOpen: ref(false),
    logPerPage: ref(10),
    logTotal: ref(0),
    logTotalPages: ref(0),
    logIsLoading: ref(false),
    logIsFetching: ref(false),
    logList: ref([]),
    onLogPageChange: vi.fn(),
  }),
}))

import InventoryPanel from '@/views/case/components/InventoryPanel.vue'

function mountPanel() {
  return mount(InventoryPanel, {
    global: {
      stubs: {
        UiStatCard: true,
        UiSearchInput: true,
        UiLoadingIcon: true,
        InventoryLogDrawer: true,
      },
    },
  })
}

/** 工具条里的「导出」按钮（aria-label 唯一，刷新按钮是「刷新」） */
function exportButton(wrapper: ReturnType<typeof mountPanel>) {
  const btn = wrapper.findAll('button').find((b) => b.attributes('aria-label') === '导出 Excel')
  expect(btn, '应存在 aria-label="导出 Excel" 的按钮').toBeTruthy()
  return btn!
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('InventoryPanel — 导出失败必须给出反馈', () => {
  it('导出失败：toast 报出接口给的失败文案（而非静默吞掉）', async () => {
    mocks.exportXlsx.mockRejectedValue(new Error('导出超上限'))
    const wrapper = mountPanel()

    await exportButton(wrapper).trigger('click')
    await flushPromises()

    expect(mocks.exportXlsx).toHaveBeenCalledTimes(1)
    expect(mocks.toastError).toHaveBeenCalledWith('导出超上限')
    // 失败后按钮必须回到可点状态，否则用户连重试都做不到
    expect(exportButton(wrapper).attributes('disabled')).toBeUndefined()
    expect(exportButton(wrapper).text()).toContain('导出')
    expect(exportButton(wrapper).text()).not.toContain('导出中')
  })

  it('导出在途：按钮禁用并显示「导出中…」，结束后恢复', async () => {
    let reject!: (e: unknown) => void
    mocks.exportXlsx.mockImplementation(() => new Promise<void>((_resolve, rej) => { reject = rej }))
    const wrapper = mountPanel()

    await exportButton(wrapper).trigger('click')
    await flushPromises()

    expect(exportButton(wrapper).attributes('disabled')).toBeDefined()
    expect(exportButton(wrapper).text()).toContain('导出中')

    // 在途期间再点一次：useExport 的并发防重必须挡下（不产生第二个导出请求）
    await exportButton(wrapper).trigger('click')
    await flushPromises()
    expect(mocks.exportXlsx).toHaveBeenCalledTimes(1)

    reject(new Error('网络中断'))
    await flushPromises()
    expect(exportButton(wrapper).attributes('disabled')).toBeUndefined()
  })
})

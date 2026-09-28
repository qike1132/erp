/**
 * 回归守卫：customer-order「Excel 批量导入 → 暂存列表」。
 *
 * 缺陷背景（2026-09-18）：后端 `GET /staging-orders` 返回
 * `{success, data:[...], total}`（StagingListResponse），而前端读的是
 * `res.staging_orders ?? res.items` —— 两个键都不存在 ⇒ `items = []` ⇒
 * 「导入成功」toast 照弹、暂存列表恒空。
 *
 * 本文件锁死三件事：
 *   1) 消费真实契约字段 `data`
 *   2) 分页取全（后端默认只给 100 条）
 *   3) 重复导入不翻倍（服务端导入前会清空会话暂存区）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, computed } from 'vue'

const mocks = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: mocks.getMock,
  post: mocks.postMock,
  put: vi.fn(),
  del: vi.fn(),
  // API 层的导入端点走 upload（multipart），此处复用 postMock 以保留原断言语义
  upload: mocks.postMock,
  download: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

// useOrderImport → useStagedItems → @tanstack/vue-query / useConfirmDialog
vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: () => ({ data: ref(undefined) }),
}))
vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: false, text: '', sub: '', type: 'warning',
    onConfirm: vi.fn(), onCancel: vi.fn(), confirm: vi.fn(async () => true),
  }),
}))

import { showToast } from '@/composables/useToast'
import { useOrderImport } from '@/views/customer-order/composables/useOrderImport'
import type { StagedItem } from '@/views/customer-order/composables/types'

/** 后端真实返回的条目形状（截取自真实响应） */
function apiRow(id: number, product: string, qty: number) {
  return {
    id,
    customer: 'MINISO国际',
    order_date: '2026-09-18 06:49',
    product_name: product,
    product_id: 20000 + id,
    quantity: qty,
    deduct_stock: false,
    deduct_quantity: 0,
    note: '',
    status: 'pending',
  }
}

function setup(staged: StagedItem[] = []) {
  const stagedItems = ref<StagedItem[]>(staged)
  const api = useOrderImport(stagedItems, computed(() => true))
  api.excelFile.value = new File(['x'], '统一导入模板.xlsx')
  return { stagedItems, api }
}

const ok = (imported: number, message = `成功导入 ${imported} 个订单到暂存区`) =>
  ({ success: true, message, imported, session_id: 'default', errors: [] })

beforeEach(() => {
  vi.clearAllMocks()
  mocks.postMock.mockResolvedValue(ok(2))
})

describe('useOrderImport — 导入后回读暂存列表', () => {
  it('消费真实契约：条目挂在 data 上（staging_orders/items 均不存在）', async () => {
    mocks.getMock.mockResolvedValue({
      success: true,
      data: [apiRow(1, '5寸鲨鱼毛绒挂件(深蓝)', 10012), apiRow(2, '19寸企鹅(灰色)', 10005)],
      total: 2,
    })

    const { stagedItems, api } = setup()
    await api.handleImport()

    expect(stagedItems.value).toHaveLength(2)
    expect(stagedItems.value[0]).toMatchObject({
      type: 'order',
      origin: 'import',
      customer: 'MINISO国际',
      productId: 20001,
      productName: '5寸鲨鱼毛绒挂件(深蓝)',
      quantity: 10012,
      date: '2026-09-18 06:49',
    })
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('成功导入 2 个订单'), 'success')
  })

  it('历史字段名兜底：仅有 staging_orders 时仍能渲染', async () => {
    mocks.getMock.mockResolvedValue({
      staging_orders: [apiRow(1, '兜底产品', 7)],
    })
    const { stagedItems, api } = setup()
    await api.handleImport()
    expect(stagedItems.value.map((i) => i.productName)).toEqual(['兜底产品'])
  })

  it('data 为空数组时不抛错、列表保持为空', async () => {
    mocks.getMock.mockResolvedValue({ success: true, data: [], total: 0 })
    const { stagedItems, api } = setup()
    await api.handleImport()
    expect(stagedItems.value).toHaveLength(0)
  })

  it('分页取全：首页满 500 条时继续请求下一页', async () => {
    const page1 = Array.from({ length: 500 }, (_, i) => apiRow(i + 1, `P${i + 1}`, 1))
    mocks.getMock
      .mockResolvedValueOnce({ success: true, data: page1, total: 501 })
      .mockResolvedValueOnce({ success: true, data: [apiRow(501, 'P501', 1)], total: 501 })

    const { stagedItems, api } = setup()
    await api.handleImport()

    expect(stagedItems.value).toHaveLength(501)
    expect(mocks.getMock).toHaveBeenCalledTimes(2)
    expect(mocks.getMock.mock.calls[1]![1]).toMatchObject({ page: 2, per_page: 500 })
  })

  it('后端 success=false 时如实报错（不再谎报成功），手工条目保留、导入条目不残留', async () => {
    mocks.postMock.mockResolvedValue({
      success: false,
      message: '没有找到"订单管理"Sheet',
      imported: 0,
      errors: [],
    })
    const { stagedItems, api } = setup([
      { uid: 'a', origin: 'manual', type: 'order', customer: 'C',
        productId: 1, productName: '手工条目', quantity: 1, date: '', note: '',
        deductStock: false, deductQuantity: 0 },
    ])
    // 失败路径同样要回读：后端在「没找到 Sheet」等失败分支里可能**已经清空**了会话暂存区，
    // 不能假定服务端状态未变（本地"上次导入的条目"必须跟着消失）。
    mocks.getMock.mockResolvedValue({ success: true, data: [], total: 0 })
    await api.handleImport()

    expect(mocks.getMock).toHaveBeenCalledTimes(1)
    expect(stagedItems.value.map((i) => i.productName)).toEqual(['手工条目'])
    expect(showToast).toHaveBeenCalledWith('没有找到"订单管理"Sheet', 'error')
  })

  it('重复导入不翻倍，且保留本页手工新增的条目', async () => {
    mocks.getMock.mockResolvedValue({
      success: true,
      data: [apiRow(1, 'A', 10), apiRow(2, 'B', 20)],
      total: 2,
    })

    const manual: StagedItem = {
      uid: 'm1', origin: 'manual', type: 'order', customer: '手工客户',
      productId: 999, productName: '手工条目', quantity: 3, date: '', note: '',
      deductStock: false, deductQuantity: 0,
    }
    const { stagedItems, api } = setup([manual])

    await api.handleImport()
    expect(stagedItems.value).toHaveLength(3) // 2 条导入 + 1 条手工

    // 第二次导入同一份文件：服务端已清空并重建，本地也必须替换而不是追加
    api.excelFile.value = new File(['x'], '统一导入模板.xlsx')
    await api.handleImport()
    expect(stagedItems.value).toHaveLength(3)
    expect(stagedItems.value.filter((i) => i.origin === 'manual')).toHaveLength(1)
    expect(stagedItems.value.filter((i) => i.origin === 'import')).toHaveLength(2)
  })

  it('导入请求体走 multipart，且并发点击只发一次请求', async () => {
    mocks.getMock.mockResolvedValue({ success: true, data: [], total: 0 })
    const { api } = setup()

    await Promise.all([api.handleImport(), api.handleImport()])
    expect(mocks.postMock).toHaveBeenCalledTimes(1)
    expect(mocks.postMock.mock.calls[0]![0]).toBe('/staging-orders/import')
    expect(mocks.postMock.mock.calls[0]![1]).toBeInstanceOf(FormData)
  })
})

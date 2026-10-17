/**
 * 出货提交 batch_no 透传测试
 *
 * 用户需求：出货指定批次后按该批次扣减。batch_no 必须穿过
 * useStockOutActions 的显式白名单映射进入提交载荷（漏写即静默丢字段）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const batchSubmitStockouts = vi.fn()
const availableShipment = vi.fn()

vi.mock('@/api', () => ({
  stockApi: {
    batchSubmitStockouts: (...a: unknown[]) => batchSubmitStockouts(...a),
    availableShipment: (...a: unknown[]) => availableShipment(...a),
  },
}))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import { useStockOutActions } from '@/views/stock/composables/useStockOutActions'

function stagedItem(over: Record<string, unknown> = {}) {
  return {
    id: 1, product_id: '11', product_name: 'P', customer: '客户A',
    date: '2026-10-16', quantity: 5, note: '', ...over,
  }
}

describe('出货提交 batch_no 透传', () => {
  beforeEach(() => {
    batchSubmitStockouts.mockReset().mockResolvedValue({ success: true, results: [{ success: true }] })
    availableShipment.mockReset().mockResolvedValue({ data: { available_quantity: 9999 } })
  })

  it('暂存项的 batch_no 进入提交载荷', async () => {
    const staged = ref([stagedItem({ batch_no: '0464628801' })])
    const { submitBatch } = useStockOutActions(staged, ref(false), () => {})
    await submitBatch()
    expect(batchSubmitStockouts).toHaveBeenCalledTimes(1)
    const payload = batchSubmitStockouts.mock.calls[0]?.[0] as Array<Record<string, unknown>>
    expect(payload[0]?.batch_no).toBe('0464628801')
  })

  it('未选批次时 batch_no 为 null（后端按整产品口径处理）', async () => {
    const staged = ref([stagedItem()])
    const { submitBatch } = useStockOutActions(staged, ref(false), () => {})
    await submitBatch()
    const payload = batchSubmitStockouts.mock.calls[0]?.[0] as Array<Record<string, unknown>>
    expect(payload[0]?.batch_no).toBeNull()
  })

  it('成功提交后清空暂存', async () => {
    const staged = ref([stagedItem({ batch_no: 'B1' })])
    const { submitBatch } = useStockOutActions(staged, ref(false), () => {})
    await submitBatch()
    expect(staged.value).toHaveLength(0)
  })
})

/**
 * H5 / H6 / M6 回归锁：出货计划创建的分组、失败草稿与产品建议竞态。
 *
 * H5：后端 `_validate_details_cross_month` 逐行拒绝与 plan_month 不一致的明细，
 *     而旧实现只按客户分组、从**首行**推导 plan_month —— 同客户跨月必然失败。
 * H6：旧实现无论成败都调 onCreated()（关闭对话框 + 刷新），失败草稿直接丢失。
 * M6：同一行连打关键字时，先发的慢响应会覆盖新关键字的结果。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mount } from '@vue/test-utils'

const planCreate = vi.fn()
const productSearch = vi.fn()
const showToast = vi.fn()

vi.mock('@/api', () => ({
  planApi: { create: (...args: unknown[]) => planCreate(...args) },
  customerApi: { activeNames: async () => ({ names: [{ id: 1, name: '客户A' }, { id: 2, name: '客户B' }] }) },
  auxApi: { productSearch: (...args: unknown[]) => productSearch(...args) },
}))

vi.mock('@/composables/useToast', () => ({ showToast: (...args: unknown[]) => showToast(...args) }))

vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({
    data: ref([{ id: 1, name: '客户A' }, { id: 2, name: '客户B' }]),
  }),
}))

import { useCreateShipmentPlan } from '@/views/purchase-plan/composables/useCreateShipmentPlan'

function withSetup<T>(composable: () => T): { result: T; wrapper: ReturnType<typeof mount> } {
  let result!: T
  const wrapper = mount(
    defineComponent({
      setup() {
        result = composable()
        return () => h('div')
      },
    }),
  )
  return { result, wrapper }
}

function line(over: Record<string, unknown> = {}) {
  return {
    customer_id: '1', product_name: '产品X', product_id: 11, barcode: 'BX',
    plan_date: '2026-10-20', quantity: 5, _showSuggest: false, ...over,
  }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

function setup(hooks: { onCreated?: () => void; onSucceeded?: () => void } = {}) {
  const open = ref(true)
  const onCreated = hooks.onCreated ?? vi.fn()
  const onSucceeded = hooks.onSucceeded ?? vi.fn()
  const { result } = withSetup(() => useCreateShipmentPlan(open, onCreated, { onSucceeded }))
  return { ...result, onCreated, onSucceeded }
}

describe('useCreateShipmentPlan', () => {
  beforeEach(() => {
    planCreate.mockReset().mockResolvedValue({})
    productSearch.mockReset().mockResolvedValue([])
    showToast.mockReset()
  })

  afterEach(() => vi.useRealTimers())

  describe('H5 按 (客户, 月份) 分组', () => {
    it('同客户同月只提交一次，plan_month 与明细一致', async () => {
      const c = setup()
      c.form.details = [line(), line({ product_name: '产品Y', product_id: 12 })]

      await c.handleSubmit()

      expect(planCreate).toHaveBeenCalledTimes(1)
      expect(planCreate.mock.calls[0]![0]).toMatchObject({
        customer_id: 1, plan_month: '2026-10', customer_name: '客户A',
      })
      expect(planCreate.mock.calls[0]![0].details).toHaveLength(2)
    })

    it('同客户跨月拆成两次提交，各自 plan_month = 该组明细月份', async () => {
      const c = setup()
      c.form.details = [
        line({ plan_date: '2026-10-20' }),
        line({ plan_date: '2026-11-02', product_name: '产品Y', product_id: 12 }),
      ]

      await c.handleSubmit()

      expect(planCreate).toHaveBeenCalledTimes(2)
      const months = planCreate.mock.calls.map((call) => call[0].plan_month).sort()
      expect(months).toEqual(['2026-10', '2026-11'])
      // 每个请求内部不得跨月（否则后端 _validate_details_cross_month 必拒）
      for (const call of planCreate.mock.calls) {
        const payload = call[0] as { plan_month: string; details: { plan_date: string }[] }
        for (const d of payload.details) {
          expect(d.plan_date.slice(0, 7)).toBe(payload.plan_month)
        }
      }
    })

    it('不同客户跨月：四个分组各自提交', async () => {
      const c = setup()
      c.form.details = [
        line({ customer_id: '1', plan_date: '2026-10-20' }),
        line({ customer_id: '1', plan_date: '2026-11-02', product_name: '产品Y', product_id: 12 }),
        line({ customer_id: '2', plan_date: '2026-10-21' }),
        line({ customer_id: '2', plan_date: '2026-11-03', product_name: '产品Y', product_id: 12 }),
      ]

      await c.handleSubmit()

      expect(planCreate).toHaveBeenCalledTimes(4)
      const combos = planCreate.mock.calls
        .map((call) => `${call[0].customer_id}|${call[0].plan_month}`)
        .sort()
      expect(combos).toEqual(['1|2026-10', '1|2026-11', '2|2026-10', '2|2026-11'])
    })
  })

  describe('H6 失败草稿保留', () => {
    it('全部成功：关闭（onCreated）且刷新（onSucceeded）', async () => {
      const c = setup()
      c.form.details = [line()]

      await c.handleSubmit()

      expect(c.onCreated).toHaveBeenCalledTimes(1)
      expect(c.onSucceeded).toHaveBeenCalledTimes(1)
    })

    it('部分失败：不关闭，只保留失败分组，并刷新已成功的', async () => {
      const c = setup()
      c.form.details = [
        line({ customer_id: '1' }),
        line({ customer_id: '2', product_name: '产品Z', product_id: 13 }),
      ]
      planCreate.mockImplementation(async (payload: { customer_id: number }) => {
        if (payload.customer_id === 2) throw { response: { data: { detail: '库存不足' } } }
        return {}
      })

      await c.handleSubmit()

      expect(c.onCreated).not.toHaveBeenCalled()
      expect(c.onSucceeded).toHaveBeenCalledTimes(1)
      expect(c.form.details).toHaveLength(1)
      expect(c.form.details[0]!.customer_id).toBe('2')
      expect(showToast).toHaveBeenCalledWith(expect.stringContaining('库存不足'), 'error')
    })

    it('全部失败：不关闭、不清空、不刷新', async () => {
      const c = setup()
      c.form.details = [line()]
      planCreate.mockRejectedValue({ response: { data: { detail: '网络错误' } } })

      await c.handleSubmit()

      expect(c.onCreated).not.toHaveBeenCalled()
      expect(c.onSucceeded).not.toHaveBeenCalled()
      expect(c.form.details).toHaveLength(1)
      expect(c.errorMsg.value).toContain('草稿已保留')
    })

    it('重试只剩失败分组（不会重复创建已成功的客户）', async () => {
      const c = setup()
      c.form.details = [
        line({ customer_id: '1' }),
        line({ customer_id: '2', product_name: '产品Z', product_id: 13 }),
      ]
      planCreate.mockImplementation(async (payload: { customer_id: number }) => {
        if (payload.customer_id === 2) throw { response: { data: { detail: 'x' } } }
        return {}
      })
      await c.handleSubmit()
      planCreate.mockClear().mockResolvedValue({})

      await c.handleSubmit()

      expect(planCreate).toHaveBeenCalledTimes(1)
      expect(planCreate.mock.calls[0]![0].customer_id).toBe(2)
    })
  })

  describe('M6 产品建议竞态', () => {
    it('旧关键字的慢响应不得覆盖新关键字的结果', async () => {
      vi.useFakeTimers()
      const c = setup()
      const first = deferred<{ id: number; name: string }[]>()
      const second = deferred<{ id: number; name: string }[]>()
      productSearch
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise)

      c.form.details[0]!.product_name = 'A'
      c.onProductInput(0)
      await vi.advanceTimersByTimeAsync(300)

      c.form.details[0]!.product_name = 'AB'
      c.onProductInput(0)
      await vi.advanceTimersByTimeAsync(300)

      second.resolve([{ id: 2, name: 'AB-结果' }])
      await vi.advanceTimersByTimeAsync(0)
      first.resolve([{ id: 1, name: 'A-结果' }])
      await vi.advanceTimersByTimeAsync(0)

      expect(c.productSuggestions[0]).toEqual([{ id: 2, name: 'AB-结果' }])
    })

    it('选中产品后在途响应不得再打开下拉', async () => {
      vi.useFakeTimers()
      const c = setup()
      const pending = deferred<{ id: number; name: string }[]>()
      productSearch.mockReturnValueOnce(pending.promise)

      c.form.details[0]!.product_name = 'ABC'
      c.onProductInput(0)
      await vi.advanceTimersByTimeAsync(300)

      c.selectProduct(0, { id: 9, name: '最终产品', barcode: 'B9' })
      pending.resolve([{ id: 1, name: 'ABC-结果' }])
      await vi.advanceTimersByTimeAsync(0)

      expect(c.productSuggestions[0]).toEqual([])
      expect(c.form.details[0]!.product_id).toBe(9)
      expect(c.form.details[0]!._showSuggest).toBe(false)
    })
  })
})

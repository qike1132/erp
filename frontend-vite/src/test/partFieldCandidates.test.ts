import { describe, it, expect, vi, beforeEach } from 'vitest'
import { effectScope, nextTick } from 'vue'

const { getPartFieldCandidates } = vi.hoisted(() => ({ getPartFieldCandidates: vi.fn() }))

vi.mock('@/api/patternRoom', () => ({ patternRoomApi: { getPartFieldCandidates } }))

import { usePartFieldCandidates } from '@/views/pattern-room/composables/usePartFieldCandidates'

/**
 * usePartFieldCandidates —— 板房字段历史候选的页面级缓存
 *
 * 覆盖「历史候选来自板房库」这条契约：经 patternRoomApi 取数、inflight 去重、
 * settled 后复用缓存、失败 fail-open 不抛。这是验收标准「输入美出现美利达」的
 * 后端来源层证明（组件层过滤另见 partFieldCombobox.test.ts）。
 */
describe('usePartFieldCandidates', () => {
  beforeEach(() => {
    getPartFieldCandidates.mockReset()
  })

  it('get() 返回后端归一化后的候选数组', async () => {
    getPartFieldCandidates.mockResolvedValue({
      success: true,
      fields: {
        supplier_name: [{ value: '美利达', count: 3 }, { value: '美丽宝', count: 1 }],
        fabric_name: [{ value: '全棉毛绒布', count: 5 }],
      },
    })
    const scope = effectScope()
    const api = scope.run(() => usePartFieldCandidates())!
    await api.load()
    await nextTick()

    expect(api.get('supplier_name')).toEqual([
      { value: '美利达', count: 3 },
      { value: '美丽宝', count: 1 },
    ])
    expect(api.get('fabric_name')).toEqual([{ value: '全棉毛绒布', count: 5 }])
    scope.stop()
  })

  it('并发多次 load() 只发一个请求（inflight 去重 + settled 复用）', async () => {
    let resolveFn: (v: unknown) => void = () => {}
    getPartFieldCandidates.mockImplementation(
      () => new Promise((res) => { resolveFn = res as (v: unknown) => void }),
    )
    const scope = effectScope()
    const api = scope.run(() => usePartFieldCandidates())!

    const p1 = api.load()
    const p2 = api.load()
    resolveFn({
      success: true,
      fields: { supplier_name: [{ value: '美利达', count: 1 }], fabric_name: [] },
    })
    await Promise.all([p1, p2])
    // settled 后再调一次，不应再发请求
    await api.load()
    expect(getPartFieldCandidates).toHaveBeenCalledTimes(1)
    scope.stop()
  })

  it('请求失败时 fail-open：get() 返回空数组且不抛', async () => {
    getPartFieldCandidates.mockRejectedValue(new Error('network down'))
    const scope = effectScope()
    const api = scope.run(() => usePartFieldCandidates())!
    await expect(api.load()).resolves.toBeUndefined()
    expect(api.get('supplier_name')).toEqual([])
    scope.stop()
  })
})

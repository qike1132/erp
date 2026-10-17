/**
 * AUD-12 回归：板房写操作失败必须有用户可见提示（2026-10-17 审计）。
 *
 * 缺陷：10 个写操作点 catch 后仅 console.error，全局拦截器只兜 401/403，
 * 用户对失败零感知（「假成功」）。本测试以版师新增为代表锁定行为。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/api/patternMaker', () => ({
  patternMakerApi: { create: mocks.create, delete: vi.fn() },
}))
vi.mock('@/composables/useToast', () => ({ showToast: mocks.showToast }))

import { usePatternRoomPatternMakers } from '@/views/pattern-room/composables/usePatternRoomPatternMakers'

describe('AUD-12 板房写失败提示', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.create.mockReset()
    mocks.showToast.mockReset()
  })

  it('新增版师失败 → showToast(error)', async () => {
    mocks.create.mockRejectedValue(new Error('500'))
    const api = usePatternRoomPatternMakers(
      ref(true),
      { confirm: vi.fn(async () => true) } as never,
    )

    await api.handleAddPatternMaker('张三')

    expect(mocks.showToast).toHaveBeenCalledWith('新增版师失败，请重试', 'error')
  })
})

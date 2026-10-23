/**
 * P1-08 回归：来料概览 KPI 必须读响应信封内层 overview。
 *
 * 后端返回 {success, overview:{...}}；此前前端把整个信封当扁平对象，
 * 桌面与移动 KPI 恒为 0。本用例锁住桌面 composable 的解包。
 */
import { describe, it, expect, vi } from 'vitest'
import { effectScope, ref } from 'vue'

const mocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
}))

vi.mock('@tanstack/vue-query', () => ({
  useQuery: mocks.useQuery,
  keepPreviousData: Symbol('keepPreviousData'),
}))
vi.mock('@/utils/queryClient', () => ({ queryClient: {} }))
vi.mock('@/api', () => ({
  materialApi: {
    progress: vi.fn(),
    overview: vi.fn(),
    distribution: vi.fn(),
    registrations: vi.fn(),
    history: vi.fn(),
  },
}))

import { useMaterialRegistrations } from '@/views/material/composables/useMaterialRegistrations'

function _key(opts: { queryKey?: unknown }): string {
  const raw = opts.queryKey as { value?: unknown } | unknown[]
  const arr = Array.isArray(raw) ? raw : (raw as { value?: unknown[] })?.value
  return String(arr?.[1] ?? '')
}

describe('来料概览信封', () => {
  it('KPI 从 overview 内层读取，而不是整个信封', () => {
    mocks.useQuery.mockImplementation((opts: { queryKey?: unknown }) => {
      const key = _key(opts)
      const data = key === 'stats-overview'
        ? { success: true, overview: { partial: 3, pending: 2, overall_progress: 42 } }
        : key === 'stats-distribution'
          ? { distribution: [{ status: 'overdue', count: 1 }] }
          : undefined
      return {
        data: { value: data },
        isLoading: { value: false },
        isFetching: { value: false },
        error: { value: null },
      }
    })

    const scope = effectScope()
    const api = scope.run(() => useMaterialRegistrations(ref('progress')))!
    try {
      expect(api.stats.value.inProgress).toBe(3)
      expect(api.stats.value.notStarted).toBe(2)
      expect(api.stats.value.overdueItems).toBe(1)
      expect(api.stats.value.overallProgress).toBe(42)
    } finally {
      scope.stop()
    }
  })
})

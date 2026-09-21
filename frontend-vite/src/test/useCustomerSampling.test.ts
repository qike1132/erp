/**
 * useCustomerSampling Hook 单元测试
 *
 * 覆盖：初始状态、loadGrouped 成功/失败路径、SWR 缓存命中/过期刷新、hasData computed
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// mock patternRoomApi
vi.mock('@/api/patternRoom', () => ({
  patternRoomApi: {
    getGroupedList: vi.fn(),
  },
}))

import { patternRoomApi } from '@/api/patternRoom'
import type { GroupedListResponse } from '@/api/patternRoom'
import { useCustomerSampling } from '../views/pattern-room/composables/useCustomerSampling'

describe('useCustomerSampling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 每个用例独立 Pinia + 清空 sessionStorage 快照，避免缓存跨用例污染
    setActivePinia(createPinia())
    if (typeof sessionStorage !== 'undefined') sessionStorage.clear()
  })

  it('初始状态正确', () => {
    const hook = useCustomerSampling()
    expect(hook.groups.value).toEqual([])
    expect(hook.loading.value).toBe(false)
    expect(hook.error.value).toBeNull()
    expect(hook.totalProjects.value).toBe(0)
    expect(hook.hasData.value).toBe(false)
  })

  it('loadGrouped 成功：更新 groups 和 totalProjects', async () => {
    const mockResponse = {
      groups: [
        {
          pattern_maker_id: 1,
          pattern_maker_name: '版师A',
          project_count: 2,
          latest_update_time: '2026-08-08 10:00:00',
          projects: [
            { id: 1, sequence_no: 'CS-20260808-0001', product_name: '产品1', current_version: 'T1', updated_at: '2026-08-08 10:00:00' },
            { id: 2, sequence_no: 'CS-20260808-0002', product_name: '产品2', current_version: 'T2', updated_at: '2026-08-08 09:00:00' },
          ],
        },
      ],
      total_projects: 2,
    }
    vi.mocked(patternRoomApi.getGroupedList).mockResolvedValue(mockResponse as unknown as GroupedListResponse)

    const hook = useCustomerSampling()
    await hook.loadGrouped()

    expect(patternRoomApi.getGroupedList).toHaveBeenCalledWith({ per_page: 20 })
    expect(hook.groups.value).toHaveLength(1)
    expect(hook.groups.value[0]!.pattern_maker_name).toBe('版师A')
    expect(hook.totalProjects.value).toBe(2)
    expect(hook.error.value).toBeNull()
    expect(hook.hasData.value).toBe(true)
  })

  it('loadGrouped 带 keyword：传递参数', async () => {
    vi.mocked(patternRoomApi.getGroupedList).mockResolvedValue({ groups: [], total_projects: 0 } as unknown as GroupedListResponse)

    const hook = useCustomerSampling()
    await hook.loadGrouped('毛绒玩具')

    expect(patternRoomApi.getGroupedList).toHaveBeenCalledWith({ keyword: '毛绒玩具', per_page: 20 })
  })

  it('loadGrouped 空白 keyword：不传递参数', async () => {
    vi.mocked(patternRoomApi.getGroupedList).mockResolvedValue({ groups: [], total_projects: 0 } as unknown as GroupedListResponse)

    const hook = useCustomerSampling()
    await hook.loadGrouped('   ')

    expect(patternRoomApi.getGroupedList).toHaveBeenCalledWith({ per_page: 20 })
  })

  it('loadGrouped 失败：设置 error 并清空数据', async () => {
    vi.mocked(patternRoomApi.getGroupedList).mockRejectedValue(new Error('网络错误'))

    const hook = useCustomerSampling()
    await hook.loadGrouped()

    expect(hook.error.value).toBe('加载打样列表失败，请稍后重试')
    expect(hook.groups.value).toEqual([])
    expect(hook.totalProjects.value).toBe(0)
    expect(hook.hasData.value).toBe(false)
  })

  it('hasData：分组有项目时为 true', () => {
    const hook = useCustomerSampling()
    hook.groups.value = [
      {
        pattern_maker_id: null,
        pattern_maker_name: '未分类',
        project_count: 1,
        latest_update_time: '',
        projects: [
          { id: 1, sequence_no: 'CS-001', product_name: '产品', product_image_url: null, product_image_thumbnail_url: null, product_image_blur_url: null, current_version: 'T1', status: 'in_progress', completed_at: null, parts_count: 0, updated_at: '' },
        ],
      },
    ]
    expect(hook.hasData.value).toBe(true)
  })

  it('hasData：分组无项目时为 false', () => {
    const hook = useCustomerSampling()
    hook.groups.value = [
      {
        pattern_maker_id: null,
        pattern_maker_name: '未分类',
        project_count: 0,
        latest_update_time: '',
        projects: [],
      },
    ]
    expect(hook.hasData.value).toBe(false)
  })

  it('SWR：新鲜缓存命中时不再发起请求，且无 loading', async () => {
    vi.mocked(patternRoomApi.getGroupedList).mockResolvedValue({ groups: [], total_projects: 0 } as unknown as GroupedListResponse)

    const hook = useCustomerSampling()
    // 首次加载：真实请求
    await hook.loadGrouped()
    expect(patternRoomApi.getGroupedList).toHaveBeenCalledTimes(1)

    // 30s 内二次加载：命中新鲜缓存，直接返回，不发请求、不触发 loading
    await hook.loadGrouped()
    expect(patternRoomApi.getGroupedList).toHaveBeenCalledTimes(1)
    expect(hook.loading.value).toBe(false)
    expect(hook.error.value).toBeNull()
  })

  it('SWR：缓存过期时先渲染旧数据并后台静默刷新（无 loading）', async () => {
    vi.useFakeTimers()
    try {
      const base = new Date('2026-01-01T00:00:00Z')
      vi.setSystemTime(base)
      const mockData = {
        groups: [
          {
            pattern_maker_id: null,
            pattern_maker_name: '未分类',
            project_count: 1,
            latest_update_time: '',
            projects: [
              { id: 1, sequence_no: 'CS-001', product_name: '产品', current_version: 'T1', updated_at: '' },
            ],
          },
        ],
        total_projects: 1,
      }
      vi.mocked(patternRoomApi.getGroupedList).mockResolvedValue(mockData as unknown as GroupedListResponse)

      const hook = useCustomerSampling()
      await hook.loadGrouped()
      expect(patternRoomApi.getGroupedList).toHaveBeenCalledTimes(1)

      // 31s 后过期：再次加载应同步渲染旧数据（不发请求前数据已就绪）
      vi.advanceTimersByTime(31_000)
      await hook.loadGrouped()
      expect(hook.groups.value).toHaveLength(1)
      expect(hook.loading.value).toBe(false)
      // 后台静默刷新已发起
      expect(patternRoomApi.getGroupedList).toHaveBeenCalledTimes(2)
      // 刷新完成后数据仍就绪
      await Promise.resolve()
      expect(hook.groups.value).toHaveLength(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it("mode='fresh'：跳过缓存强制请求", async () => {
    vi.mocked(patternRoomApi.getGroupedList).mockResolvedValue({ groups: [], total_projects: 0 } as unknown as GroupedListResponse)

    const hook = useCustomerSampling()
    await hook.loadGrouped()
    await hook.loadGrouped(undefined, undefined, 1, 'fresh')

    expect(patternRoomApi.getGroupedList).toHaveBeenCalledTimes(2)
    expect(hook.loading.value).toBe(false)
  })
})

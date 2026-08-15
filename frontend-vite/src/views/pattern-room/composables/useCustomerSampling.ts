/**
 * useCustomerSampling — 客户分组列表 Hook
 *
 * 封装按客户分组聚合查询的状态管理与 API 调用（含分页）。
 * 对应 design.md 2.4.6 E1。
 */
import { ref, computed } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type { PatternMakerGroup } from '@/api/patternRoom'

export function useCustomerSampling() {
  /** 版师分组列表（按组内最新更新时间倒序，"未分类"在最后） */
  const groups = ref<PatternMakerGroup[]>([])
  /** 加载中 */
  const loading = ref(false)
  /** 错误信息 */
  const error = ref<string | null>(null)
  /** 总项目数 */
  const totalProjects = ref(0)
  /** 分页：总条数 */
  const total = ref(0)
  /** 分页：总页数 */
  const pages = ref(0)
  /** 分页：当前页 */
  const currentPage = ref(1)
  /** 每页条数 */
  const perPage = 20

  /**
   * 加载按客户分组聚合的打样项目列表（分页）
   * @param keyword 关键词（匹配序列号/产品名）
   * @param status 状态筛选（in_progress/completed/cancelled），为空表示全部
   * @param page 页码（默认 1）
   */
  async function loadGrouped(keyword?: string, status?: string, page?: number): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const params: { keyword?: string; status?: string; page?: number; per_page?: number } = {
        per_page: perPage,
      }
      if (keyword && keyword.trim()) params.keyword = keyword.trim()
      if (status) params.status = status
      if (page) params.page = page
      const res = await patternRoomApi.getGroupedList(params)
      groups.value = res.groups ?? []
      totalProjects.value = res.total_projects ?? 0
      total.value = res.total ?? 0
      pages.value = res.pages ?? 0
      currentPage.value = res.current_page ?? 1
    } catch (e) {
      console.error('[useCustomerSampling] 加载分组列表失败:', e)
      error.value = '加载打样列表失败，请稍后重试'
      groups.value = []
      totalProjects.value = 0
      total.value = 0
      pages.value = 0
      currentPage.value = 1
    } finally {
      loading.value = false
    }
  }

  /** 是否有数据 */
  const hasData = computed(() => groups.value.some((g) => g.projects.length > 0))

  return {
    groups,
    loading,
    error,
    totalProjects,
    total,
    pages,
    currentPage,
    perPage,
    hasData,
    loadGrouped,
  }
}

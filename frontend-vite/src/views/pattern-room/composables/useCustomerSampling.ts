/**
 * useCustomerSampling — 客户分组列表 Hook
 *
 * 封装按客户分组聚合查询的状态管理与 API 调用。
 * 对应 design.md 2.4.6 E1。
 */
import { ref, computed } from 'vue'
import { patternRoomApi } from '@/api/patternRoom'
import type { CustomerGroup } from '@/api/patternRoom'

export function useCustomerSampling() {
  /** 客户分组列表（按组内最新更新时间倒序，"未分类"在最后） */
  const groups = ref<CustomerGroup[]>([])
  /** 加载中 */
  const loading = ref(false)
  /** 错误信息 */
  const error = ref<string | null>(null)
  /** 总项目数 */
  const totalProjects = ref(0)

  /**
   * 加载按客户分组聚合的打样项目列表
   * @param keyword 关键词（匹配序列号/产品名）
   */
  async function loadGrouped(keyword?: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const params = keyword && keyword.trim() ? { keyword: keyword.trim() } : undefined
      const res = await patternRoomApi.getGroupedList(params)
      groups.value = res.groups ?? []
      totalProjects.value = res.total_projects ?? 0
    } catch (e) {
      console.error('[useCustomerSampling] 加载分组列表失败:', e)
      error.value = '加载打样列表失败，请稍后重试'
      groups.value = []
      totalProjects.value = 0
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
    hasData,
    loadGrouped,
  }
}
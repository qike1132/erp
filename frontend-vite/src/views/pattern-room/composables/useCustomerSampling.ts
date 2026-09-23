/**
 * useCustomerSampling — 客户分组列表 Hook
 *
 * 封装按客户分组聚合查询的状态管理与 API 调用（含分页）。
 * 对应 design.md 2.4.6 E1。
 *
 * 数据层接入 patternRoom Store（SWR 缓存）：
 * - 30s 内新鲜数据直接返回，不发请求 → 多次进入打样间不再重复加载
 * - 缓存过期时先展示旧数据 + 后台静默刷新，不闪「加载中」
 * - mode='fresh' 跳过缓存（写操作 / 筛选切换后保证数据新鲜）
 */
import { ref, computed } from 'vue'
import type { PatternMakerGroup, GroupedListResponse, ProjectStatus } from '@/api/patternRoom'
import { usePatternRoomStore, makeGroupedKey, resolveSwr, PATTERN_ROOM_PAGE_SIZE } from '@/stores/patternRoom'

/**
 * 分组列表加载模式（替代原先两个布尔标志参数，调用点无需回读实现即可读懂语义）：
 * - cache：优先命中 SWR 缓存（默认；新鲜直接返回，过期先渲染旧数据再后台刷新）
 * - fresh：跳过缓存强制请求，前台 loading（写操作 / 用户主动筛选后）
 * - silent：跳过缓存强制请求，且不置 loading（卡片级增量写操作后的列表同步，
 *   避免 v-if 分支交换导致整个列表面板摘除重挂载、丢失滚动位置与组内分页状态）
 */
export type GroupedLoadMode = 'cache' | 'fresh' | 'silent'

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
  /** 每页条数（与 store 请求分页共用同一常量，避免两处各写 20） */
  const perPage = PATTERN_ROOM_PAGE_SIZE

  const store = usePatternRoomStore()

  /** 最近一次前台加载对应的查询 key：后台刷新结果仅在该 key 仍是当前视图时应用，
   *  避免用户切换筛选/翻页后旧响应回写覆盖新数据 */
  let viewKey = ''

  /** 竞态保护：每次发请求递增，响应回来时若不匹配则忽略。
   *  覆盖 force 强刷路径：请求进行中用户切换筛选/翻页时，旧响应不得覆盖新数据，
   *  并发请求的 loading 状态也以最新一次请求为准。 */
  let _requestId = 0

  /** 将接口响应写入本地状态 */
  function applyData(res: GroupedListResponse) {
    groups.value = res.groups ?? []
    totalProjects.value = res.total_projects ?? 0
    total.value = res.total ?? 0
    pages.value = res.pages ?? 0
    currentPage.value = res.current_page ?? 1
  }

  /**
   * 加载按客户分组聚合的打样项目列表（分页）
   * @param keyword 关键词（匹配序列号/产品名）
   * @param status 状态筛选（in_progress/completed/cancelled），为空表示全部
   * @param page 页码（默认 1）
   * @param mode 加载模式，默认 'cache'。语义见 GroupedLoadMode 定义。
   */
  async function loadGrouped(
    keyword?: string,
    status?: ProjectStatus,
    page?: number,
    mode: GroupedLoadMode = 'cache',
  ): Promise<void> {
    // 由 mode 推导原有两个开关，保持内部逻辑与行为完全不变
    const force = mode !== 'cache'
    const silent = mode === 'silent'
    const reqId = ++_requestId
    const key = makeGroupedKey(keyword, status, page)
    // 三态路径均需更新 viewKey：否则 force 路径下遗留的旧 key 会让在途的
    // 后台刷新误判"视图未变"而把旧筛选的数据回写到新视图
    viewKey = key
    // 非强制时优先命中缓存：策略由 store 的 resolveSwr 统一实现（KD-1），
    // 语义为「新鲜 → 直接渲染零请求；过期 → 先渲染旧数据 + 后台静默刷新；未命中 → 前台加载」
    if (!force) {
      const outcome = await resolveSwr({
        getSnapshot: () => store.getGroupedSnapshot(keyword, status, page),
        fetch: () => store.fetchGrouped(keyword, status, page),
        apply: applyData,
        // 仅当视图仍是该查询（且未被更新的请求取代）时应用后台刷新结果
        isCurrent: () => viewKey === key && reqId === _requestId,
        logLabel: '[useCustomerSampling] 后台刷新分组列表失败',
      })
      if (outcome !== 'miss') return
    }

    if (!silent) loading.value = true
    error.value = null
    try {
      const res = await store.fetchGrouped(keyword, status, page)
      // 竞态守卫：请求进行中用户已切换筛选/翻页（发起了新请求）时，丢弃本次响应
      if (reqId !== _requestId) return
      if (res) applyData(res)
    } catch (e) {
      if (reqId !== _requestId) return
      if (silent) {
        // 静默刷新失败：写操作本身已成功，保留当前视图数据，
        // 避免错误态再把整个面板交换成错误提示；下次激活/操作会重新校验
        console.error('[useCustomerSampling] 静默刷新分组列表失败:', e)
        return
      }
      console.error('[useCustomerSampling] 加载分组列表失败:', e)
      error.value = '加载打样列表失败，请稍后重试'
      groups.value = []
      totalProjects.value = 0
      total.value = 0
      pages.value = 0
      currentPage.value = 1
    } finally {
      // 仅当本次仍是最新的前台请求时才复位 loading，避免并发请求互相干扰
      if (!silent && reqId === _requestId) loading.value = false
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
/**
 * patternRoom — 打样间数据缓存 Store（SWR: Stale-While-Revalidate）
 *
 * 解决「每次进入 /pattern-room 都要重新请求全部数据并显示加载中」的问题：
 * - 分组列表 / 版师列表 / 项目详情等数据集中缓存，30s 内为新鲜数据，直接返回不发请求
 * - 缓存过期时「先渲染旧数据 + 后台静默刷新」，不再闪 loading
 * - 当前页关键数据（默认分组列表 + 版师列表）写入 sessionStorage，
 *   页面刷新（F5）后仍可命中缓存，二次进入打样间 0 请求、0 加载态
 * - 写操作（增删改）成功后通过 invalidate* / force 参数强制刷新，保证数据一致
 *
 * 对比方案：Dashboard 使用 TanStack Vue Query 的 SWR（staleTime: 30s），
 * 本 store 为 pattern-room 提供同等能力，且不改动现有 composable 的对外 API。
 */
import { defineStore } from 'pinia'
import { patternRoomApi, type GroupedListResponse, type ProjectStatus } from '@/api/patternRoom'
import type { GroupedListParams } from '@/api/patternRoom'
import { patternMakerApi, type PatternMaker } from '@/api/patternMaker'

/** 缓存新鲜期：30s 内直接命中，不发请求（分组列表与版师列表共用同一新鲜窗口） */
export const PATTERN_ROOM_STALE_MS = 30_000
/** 分组列表每页条数（分页请求与本地分页状态共用，避免两处各写 20） */
export const PATTERN_ROOM_PAGE_SIZE = 20
/** sessionStorage 持久化 key（仅当前标签页有效，关闭标签页自动清除） */
const SESSION_KEY = 'fb_pattern_room_cache_v1'
/** 持久化体积上限：超限跳过写入，避免撑爆 sessionStorage（默认 5MB） */
const MAX_PERSIST_CHARS = 300_000
/**
 * 持久化快照最长可恢复年龄：必须小于图片签名 URL 的有效期（后端
 * signed_urls.sign_upload_url 默认 ttl=3600s，nginx secure_link 过期判 410）。
 * 分组列表里内嵌 product_image_url 等限时签名链接；标签页闲置超过有效期后再
 * 进入，恢复出的旧 URL 会 410，卡片双双加载失败切到占位图。超过本年龄的快照
 * 直接作废（走正常前台加载），不再享受「F5 零请求」。
 */
const PERSISTED_MAX_AGE_MS = 45 * 60 * 1000

interface GroupedCacheEntry {
  data: GroupedListResponse
  loadedAt: number
}

interface MakersCacheEntry {
  data: PatternMaker[]
  loadedAt: number
}

interface PersistedShape {
  grouped: Record<string, GroupedCacheEntry>
  makers: MakersCacheEntry | null
  savedAt: number
}

/** 分组查询缓存 key：归一化 status/keyword/page，避免等价请求产生多个缓存条目。
 *  导出供 useCustomerSampling 复用，避免"视图守卫 key"与"缓存 key"两处规则漂移。 */
export function makeGroupedKey(keyword?: string, status?: ProjectStatus, page?: number): string {
  return JSON.stringify([status ?? 'in_progress', (keyword ?? '').trim(), page ?? 1])
}

/** SWR 命中结果：cache-fresh 无需请求；cache-stale 已渲染旧数据并已发起后台刷新；miss 需前台加载 */
export type SwrOutcome = 'cache-fresh' | 'cache-stale' | 'miss'

/**
 * 统一的 SWR 读取策略（KD-1：消除 useCustomerSampling 与 usePatternRoomPatternMakers
 * 各自实现一遍的"新鲜→直取／过期→先渲染旧数据再后台刷新"分支）。
 *
 * 调用方职责：提供快照读取、拉取、数据落地与"当前视图是否仍有效"的守卫。
 * 本函数不持有状态，仅编排既有 store 能力，因此行为与原先两处内联实现完全一致。
 *
 * @param getSnapshot 读取缓存快照（无缓存返回 null）
 * @param fetch 真实请求（含并发去重，由 store 提供）
 * @param apply 将数据写入调用方状态
 * @param isCurrent 后台刷新返回时判断视图是否仍是发起时的查询，避免旧响应覆盖新数据
 * @param logLabel 后台刷新失败时的完整日志前缀（由调用方保持各自原有文案）
 */
export async function resolveSwr<T>(opts: {
  getSnapshot: () => { data: T; isFresh: boolean } | null
  fetch: () => Promise<T | null>
  apply: (data: T) => void
  isCurrent: () => boolean
  logLabel: string
}): Promise<SwrOutcome> {
  const { getSnapshot, fetch, apply, isCurrent, logLabel } = opts

  const snapshot = getSnapshot()
  if (!snapshot) return 'miss'

  // 命中缓存：先渲染（可能是旧数据，保证不闪 loading）
  apply(snapshot.data)
  if (snapshot.isFresh) return 'cache-fresh'

  // 过期缓存：后台静默刷新，仅在视图仍是该查询时应用结果
  void fetch()
    .then((data) => {
      if (data && isCurrent()) apply(data)
    })
    .catch((e) => {
      console.error(`${logLabel}:`, e)
    })
  return 'cache-stale'
}

function loadPersisted(): PersistedShape | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const shape = JSON.parse(raw) as PersistedShape
    if (
      !shape
      || typeof shape !== 'object'
      || !shape.grouped
      || typeof shape.grouped !== 'object'
      || typeof shape.savedAt !== 'number'
    ) {
      return null
    }
    // 快照里内嵌的限时签名图片 URL 已随时间过期（410）：超龄快照整体作废并清除，
    // 避免恢复后先渲染出必然加载失败的旧图、再把卡片失败状态"焊死"在占位图上
    if (Date.now() - shape.savedAt > PERSISTED_MAX_AGE_MS) {
      try {
        sessionStorage.removeItem(SESSION_KEY)
      } catch { /* 静默 */ }
      return null
    }
    return shape
  } catch {
    // 隐私模式 / 数据损坏时静默降级（不缓存）
    return null
  }
}

export const usePatternRoomStore = defineStore('patternRoom', () => {
  /** 分组列表缓存（内存，按查询条件分 key） */
  let groupedCache: Record<string, GroupedCacheEntry> = {}
  /** 版师列表缓存（内存） */
  let patternMakersCache: MakersCacheEntry | null = null
  /** 同 key 并发请求去重（跨组件实例、跨挂载共享） */
  const _inflightGrouped = new Map<string, Promise<GroupedListResponse>>()
  let _inflightMakers: Promise<PatternMaker[]> | null = null

  // ==================== 启动时从 sessionStorage 恢复快照 ====================
  const persisted = loadPersisted()
  if (persisted) {
    groupedCache = { ...persisted.grouped }
    if (persisted.makers) patternMakersCache = persisted.makers
  }

  // ==================== 持久化（仅默认查询条目 + 版师列表，控制体积） ====================
  function persist(): void {
    try {
      const defaultKey = makeGroupedKey(undefined, 'in_progress', 1)
      const shape: PersistedShape = { grouped: {}, makers: null, savedAt: Date.now() }
      const entry = groupedCache[defaultKey]
      if (entry) shape.grouped[defaultKey] = entry
      if (patternMakersCache) shape.makers = patternMakersCache
      const raw = JSON.stringify(shape)
      if (raw.length > MAX_PERSIST_CHARS) return
      sessionStorage.setItem(SESSION_KEY, raw)
    } catch {
      // 写入失败（如隐私模式）静默降级
    }
  }

  // ==================== 分组列表 ====================

  /** 读取分组列表缓存快照；无缓存返回 null，存在则附带是否新鲜标记 */
  function getGroupedSnapshot(
    keyword?: string,
    status?: ProjectStatus,
    page?: number,
  ): { data: GroupedListResponse; isFresh: boolean } | null {
    const entry = groupedCache[makeGroupedKey(keyword, status, page)]
    if (!entry) return null
    return { data: entry.data, isFresh: Date.now() - entry.loadedAt < PATTERN_ROOM_STALE_MS }
  }

  /**
   * 请求分组列表并写入缓存（并发去重）。
   * 失败时 reject，由调用方决定前台报错或后台静默。
   */
  async function fetchGrouped(
    keyword?: string,
    status?: ProjectStatus,
    page?: number,
  ): Promise<GroupedListResponse | null> {
    const key = makeGroupedKey(keyword, status, page)
    const existing = _inflightGrouped.get(key)
    if (existing) return existing

    const params: GroupedListParams = { per_page: PATTERN_ROOM_PAGE_SIZE }
    const kw = (keyword ?? '').trim()
    if (kw) params.keyword = kw
    // 未显式传 status 时不发送（后端默认 in_progress），保持调用方原有请求契约
    if (status) params.status = status
    if (page) params.page = page

    const p = patternRoomApi.getGroupedList(params)
      .then((res) => {
        groupedCache = { ...groupedCache, [key]: { data: res, loadedAt: Date.now() } }
        persist()
        return res
      })
      .catch((e: unknown) => {
        console.error('[patternRoomStore] 加载分组列表失败:', e)
        throw e
      })
    _inflightGrouped.set(key, p)
    p.finally(() => {
      _inflightGrouped.delete(key)
    }).catch(() => { /* 错误已由调用方处理 */ })
    return p
  }

  /** 清除全部分组列表缓存（写操作后调用，强制下次走真实请求） */
  function invalidateGrouped(): void {
    groupedCache = {}
    // 同步重写 sessionStorage 快照，避免失效后 F5 恢复出写操作前的旧数据
    persist()
  }

  // ==================== 版师列表 ====================

  /** 读取版师列表缓存快照 */
  function getMakersSnapshot(): { data: PatternMaker[]; isFresh: boolean } | null {
    if (!patternMakersCache) return null
    return {
      data: patternMakersCache.data,
      isFresh: Date.now() - patternMakersCache.loadedAt < PATTERN_ROOM_STALE_MS,
    }
  }

  /** 请求版师列表并写入缓存（并发去重） */
  async function fetchMakers(): Promise<PatternMaker[] | null> {
    if (_inflightMakers) return _inflightMakers
    const p = patternMakerApi.list()
      .then((res) => {
        const data = res.items ?? []
        patternMakersCache = { data, loadedAt: Date.now() }
        persist()
        return data
      })
      .catch((e: unknown) => {
        console.error('[patternRoomStore] 加载版师列表失败:', e)
        throw e
      })
    _inflightMakers = p
    p.finally(() => {
      _inflightMakers = null
    }).catch(() => { /* 错误已由调用方处理 */ })
    return p
  }

  /** 清除版师列表缓存（新增/删除版师后调用） */
  function invalidateMakers(): void {
    patternMakersCache = null
    persist()
  }

  // ==================== 预取（登录/首屏时调用） ====================

  /**
   * 预取打样间首页数据（默认分组列表 + 版师列表），填充缓存。
   * 登录成功后并行调用；用户首次进入 /pattern-room 时命中缓存 → 0ms 渲染。
   * 内部吞掉错误，不影响调用方流程。
   */
  async function prefetch(): Promise<void> {
    // 打样间读端点要求 customer_sampling_view 或 customer_sampling_manage
    // （后端 require_any_permission）；无权限用户一律不预取 —— 否则每次登录都会
    // 发出一次注定 403 的 grouped-list 请求，触发全局 axios 拦截器的「权限不足」
    // 弹窗（表现为「其他用户一登录就显示无权限」）。
    // 动态 import 避免与 auth store 形成循环依赖（auth store 顶部引用了本 store 的 clear）
    const { useAuthStore } = await import('@/stores/auth')
    const auth = useAuthStore()
    if (!auth.hasAnyPermission(['customer_sampling_view', 'customer_sampling_manage'])) return

    const snap = getGroupedSnapshot(undefined, 'in_progress', 1)
    if (!snap || !snap.isFresh) {
      void fetchGrouped(undefined, 'in_progress', 1).catch(() => { /* 预取失败静默 */ })
    }
    // 版师列表接口比读权限更严：只认 customer_sampling_manage，单独判定
    if (!auth.hasPermission('customer_sampling_manage')) return
    const makers = getMakersSnapshot()
    if (!makers || !makers.isFresh) {
      void fetchMakers().catch(() => { /* 预取失败静默 */ })
    }
  }

  /** 清空缓存（退出登录时调用，避免跨账号数据残留） */
  function clear(): void {
    groupedCache = {}
    patternMakersCache = null
    _inflightGrouped.clear()
    _inflightMakers = null
    try {
      sessionStorage.removeItem(SESSION_KEY)
    } catch { /* 静默 */ }
  }

  return {
    getGroupedSnapshot,
    fetchGrouped,
    invalidateGrouped,
    getMakersSnapshot,
    fetchMakers,
    invalidateMakers,
    prefetch,
    clear,
  }
})
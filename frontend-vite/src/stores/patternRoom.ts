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
import { patternRoomApi, type GroupedListResponse } from '@/api/patternRoom'
import type { GroupedListParams } from '@/api/patternRoom'
import { patternMakerApi, type PatternMaker } from '@/api/patternMaker'

/** 缓存新鲜期：30s 内直接命中，不发请求 */
const GROUPED_STALE_MS = 30_000
const MAKERS_STALE_MS = 30_000
/** sessionStorage 持久化 key（仅当前标签页有效，关闭标签页自动清除） */
const SESSION_KEY = 'fb_pattern_room_cache_v1'
/** 持久化体积上限：超限跳过写入，避免撑爆 sessionStorage（默认 5MB） */
const MAX_PERSIST_CHARS = 300_000

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

/** 分组查询缓存 key：归一化 status/keyword/page，避免等价请求产生多个缓存条目 */
function makeGroupedKey(keyword?: string, status?: string, page?: number): string {
  return JSON.stringify([status ?? 'in_progress', (keyword ?? '').trim(), page ?? 1])
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
    status?: string,
    page?: number,
  ): { data: GroupedListResponse; isFresh: boolean } | null {
    const entry = groupedCache[makeGroupedKey(keyword, status, page)]
    if (!entry) return null
    return { data: entry.data, isFresh: Date.now() - entry.loadedAt < GROUPED_STALE_MS }
  }

  /**
   * 请求分组列表并写入缓存（并发去重）。
   * 失败时 reject，由调用方决定前台报错或后台静默。
   */
  async function fetchGrouped(
    keyword?: string,
    status?: string,
    page?: number,
  ): Promise<GroupedListResponse | null> {
    const key = makeGroupedKey(keyword, status, page)
    const existing = _inflightGrouped.get(key)
    if (existing) return existing

    const params: GroupedListParams = { per_page: 20 }
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
      isFresh: Date.now() - patternMakersCache.loadedAt < MAKERS_STALE_MS,
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
    const snap = getGroupedSnapshot(undefined, 'in_progress', 1)
    if (!snap || !snap.isFresh) {
      void fetchGrouped(undefined, 'in_progress', 1).catch(() => { /* 预取失败静默 */ })
    }
    const makers = getMakersSnapshot()
    if (!makers || !makers.isFresh) {
      // 版师列表接口要求 customer_sampling_manage 权限，无权限用户不预取，避免每次登录产生 403 噪音
      // 动态 import 避免与 auth store 形成循环依赖（auth store 顶部引用了本 store 的 clear）
      const { useAuthStore } = await import('@/stores/auth')
      if (!useAuthStore().hasPermission('customer_sampling_manage')) return
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
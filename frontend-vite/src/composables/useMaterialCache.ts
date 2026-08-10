/**
 * useMaterialCache — 来料页面数据缓存层
 *
 * 策略：stale-while-revalidate（SWR）
 * - 首次加载：立即返回缓存数据渲染页面，同时在后台发起网络请求更新
 * - 无缓存时：正常发起请求，无额外开销
 * - 缓存有效期 60s，超过后仍返回旧数据但标记为过期
 * - 使用 sessionStorage 跨路由导航保持缓存，关闭标签页后清除
 *
 * 效果：用户在 tab 间切换或返回页面时，直接看到内容，无需等待 2s loading
 */
import type { Registration } from '@/api/material'

const CACHE_PREFIX = 'mat_cache_v2_'  // v2: 包含 po_create_time + sku_items 的完整数据结构
const CACHE_TTL_MS = 60_000 // 60s 缓存有效期

interface CacheEntry<T> {
  data: T
  timestamp: number
}

function buildKey(params: Record<string, unknown>): string {
  const sorted: Record<string, unknown> = {}
  for (const k of Object.keys(params).sort()) {
    sorted[k] = params[k]
  }
  return CACHE_PREFIX + JSON.stringify(sorted)
}

function getCache<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const entry: CacheEntry<T> = JSON.parse(raw)
    const age = Date.now() - entry.timestamp
    if (age > CACHE_TTL_MS * 2) {
      // 超过 2 倍 TTL，视为无效
      sessionStorage.removeItem(key)
      return null
    }
    return entry.data
  } catch {
    sessionStorage.removeItem(key)
    return null
  }
}

function setCache<T>(key: string, data: T): void {
  try {
    const entry: CacheEntry<T> = { data, timestamp: Date.now() }
    // 限制缓存条目数，防止 sessionStorage 撑满
    const cacheKeys = Object.keys(sessionStorage).filter(k => k.startsWith(CACHE_PREFIX))
    if (cacheKeys.length > 20) {
      // 按时间排序，删除最旧的
      const sorted = cacheKeys
        .map(k => {
          try {
            const ts = JSON.parse(sessionStorage.getItem(k) || '{"timestamp":0}').timestamp
            return { key: k, ts: typeof ts === 'number' ? ts : 0 }
          } catch {
            sessionStorage.removeItem(k)
            return null
          }
        })
        .filter((x): x is { key: string; ts: number } => x !== null)
        .sort((a, b) => a.ts - b.ts)
      for (let i = 0; i < sorted.length - 20; i++) {
        const item = sorted[i]
        if (item) sessionStorage.removeItem(item.key)
      }
    }
    sessionStorage.setItem(key, JSON.stringify(entry))
  } catch {
    // sessionStorage 写入失败（如存储满），静默降级
  }
}

export interface CacheResult<T> {
  /** 缓存数据，可能为 null */
  cached: T | null
  /** 是否为有效缓存（未过期） */
  fresh: boolean
}

/**
 * 读取缓存数据
 * @returns cached: 缓存数据; fresh: 是否在 TTL 内
 */
export function readMaterialCache<T = { registrations: Registration[]; pages: number; total: number }>(
  type: 'progress' | 'history',
  params: Record<string, unknown>,
): CacheResult<T> {
  const key = buildKey({ type, ...params })
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return { cached: null, fresh: false }
    const entry: CacheEntry<T> = JSON.parse(raw)
    const age = Date.now() - entry.timestamp
    if (age > CACHE_TTL_MS * 2) {
      sessionStorage.removeItem(key)
      return { cached: null, fresh: false }
    }
    return { cached: entry.data, fresh: age <= CACHE_TTL_MS }
  } catch {
    sessionStorage.removeItem(key)
    return { cached: null, fresh: false }
  }
}

/**
 * 写入缓存数据
 */
export function writeMaterialCache<T>(
  type: 'progress' | 'history',
  params: Record<string, unknown>,
  data: T,
): void {
  const key = buildKey({ type, ...params })
  setCache(key, data)
}

/**
 * 清除指定类型的缓存
 */
export function clearMaterialCache(type: 'progress' | 'history'): void {
  const keys = Object.keys(sessionStorage).filter(k => k.startsWith(CACHE_PREFIX))
  keys.forEach(k => {
    try {
      const parsed = JSON.parse(k.slice(CACHE_PREFIX.length))
      if (parsed.type === type) sessionStorage.removeItem(k)
    } catch { /* skip invalid keys */ }
  })
}

/**
 * 清除所有来料缓存
 */
export function clearAllMaterialCache(): void {
  const keys = Object.keys(sessionStorage).filter(k => k.startsWith(CACHE_PREFIX))
  keys.forEach(k => sessionStorage.removeItem(k))
}

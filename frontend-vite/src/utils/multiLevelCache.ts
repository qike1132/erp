/**
 * 前端多级缓存 L1(内存Map) + L2(localStorage)
 * 用于列表数据、字典数据缓存，减少网络请求
 */

interface CacheEntry<T> { data: T; expireAt: number; createdAt: number }

export class MultiLevelCache {
  private l1: Map<string, CacheEntry<any>> = new Map()
  private l1Hits = 0; private l2Hits = 0; private misses = 0
  constructor(
    private l1MaxSize = 500,
    private l1TtlMs = 30_000,
    private l2TtlMs = 300_000,
    private l2Prefix = 'erp_cache:',
  ) {}

  get<T>(key: string): T | null {
    const now = Date.now()
    const e1 = this.l1.get(key)
    if (e1 && e1.expireAt > now) { this.l1Hits++; return e1.data as T }
    if (e1) this.l1.delete(key)
    try {
      const raw = localStorage.getItem(this.l2Prefix + key)
      if (raw) {
        const entry: CacheEntry<T> = JSON.parse(raw)
        if (entry.expireAt > now) {
          this.l2Hits++
          this._setL1(key, entry.data, Math.min(entry.expireAt - now, this.l1TtlMs))
          return entry.data
        }
        localStorage.removeItem(this.l2Prefix + key)
      }
    } catch {}
    this.misses++; return null
  }

  set<T>(key: string, data: T, ttlMs?: number): void {
    const now = Date.now()
    const ttl = ttlMs ?? this.l1TtlMs
    this._setL1(key, data, ttl)
    try {
      const entry: CacheEntry<T> = { data, expireAt: now + Math.max(ttl, this.l2TtlMs), createdAt: now }
      const s = JSON.stringify(entry)
      if (s.length < 100_000) localStorage.setItem(this.l2Prefix + key, s)
    } catch { this._evictL2() }
  }

  invalidate(key: string): void {
    this.l1.delete(key)
    try { localStorage.removeItem(this.l2Prefix + key) } catch {}
  }

  invalidatePattern(pattern: string): number {
    let count = 0
    const regex = new RegExp(pattern.replace(/\*/g, '.*'))
    for (const k of Array.from(this.l1.keys())) if (regex.test(k)) { this.l1.delete(k); count++ }
    try {
      const p = this.l2Prefix
      for (let i = 0; i < localStorage.length; i++) {
        const sk = localStorage.key(i)
        if (sk?.startsWith(p) && regex.test(sk.slice(p.length))) { localStorage.removeItem(sk); count++ }
      }
    } catch {}
    return count
  }

  getStats() {
    const t = this.l1Hits + this.l2Hits + this.misses
    return { l1Size: this.l1.size, l1Hits: this.l1Hits, l2Hits: this.l2Hits, misses: this.misses, hitRate: t > 0 ? (this.l1Hits + this.l2Hits) / t : 0 }
  }

  clear(): void {
    this.l1.clear()
    try {
      const p = this.l2Prefix
      for (let i = localStorage.length - 1; i >= 0; i--) { const k = localStorage.key(i); if (k?.startsWith(p)) localStorage.removeItem(k) }
    } catch {}
    this.l1Hits = 0; this.l2Hits = 0; this.misses = 0
  }

  private _setL1<T>(key: string, data: T, ttlMs: number): void {
    if (this.l1.size >= this.l1MaxSize) this._evictL1()
    this.l1.set(key, { data, expireAt: Date.now() + ttlMs, createdAt: Date.now() })
  }

  private _evictL1(): void {
    const entries = Array.from(this.l1.entries()).sort((a, b) => a[1].expireAt - b[1].expireAt)
    for (let i = 0; i < Math.max(1, Math.floor(entries.length * 0.25)); i++) {
      const entry = entries[i]
      if (entry) this.l1.delete(entry[0])
    }
  }

  private _evictL2(): void {
    try {
      const p = this.l2Prefix; const items: { k: string; t: number }[] = []
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (k?.startsWith(p)) { try { items.push({ k, t: JSON.parse(localStorage.getItem(k) ?? '{}').createdAt ?? 0 }) } catch {} }
      }
      items.sort((a, b) => a.t - b.t)
      for (let i = 0; i < Math.max(1, Math.floor(items.length * 0.25)); i++) {
        const item = items[i]
        if (item) localStorage.removeItem(item.k)
      }
    } catch {}
  }
}

export const appCache = new MultiLevelCache()

export function withCache<T>(key: string, fetcher: () => Promise<T>, ttlMs = 30_000): Promise<T> {
  const cached = appCache.get<T>(key)
  if (cached !== null) return Promise.resolve(cached)
  return fetcher().then((data) => { appCache.set(key, data, ttlMs); return data })
}

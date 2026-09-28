/**
 * Service Worker 运行时缓存清理。
 *
 * 登出时必须清掉 API 缓存：共用终端上，后一位用户可能读到前一位用户的缓存响应
 * （sessionStorage 与 Vue Query 缓存已由 auth store 清理，Workbox 的 Cache Storage
 * 不在其列）。详见 src/test/swCache.test.ts 的背景说明。
 */

/** 本项目 API 运行时缓存的名称前缀（Workbox cacheName 以 `api-` 开头）。 */
const API_CACHE_PREFIX = 'api-'

/** 只声明用到的两个方法，避免依赖 DOM 类型细节、也便于测试注入。 */
type CacheStorageLike = {
  keys(): Promise<string[]>
  delete(name: string): Promise<boolean>
}

function cacheStorage(): CacheStorageLike | null {
  const storage = (globalThis as { caches?: CacheStorageLike }).caches
  return storage && typeof storage.keys === 'function' ? storage : null
}

/**
 * 删除所有 `api-*` 运行时缓存；环境不支持或失败时静默返回（不得影响登出流程）。
 */
export async function purgeApiCaches(): Promise<void> {
  const storage = cacheStorage()
  if (!storage) return

  try {
    const names = await storage.keys()
    await Promise.all(
      names.filter((name) => name.startsWith(API_CACHE_PREFIX)).map((name) => storage.delete(name)),
    )
  } catch {
    /* 清缓存失败不应阻塞登出 */
  }
}

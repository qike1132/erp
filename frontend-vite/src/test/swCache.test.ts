/**
 * 登出时清理 Service Worker 的 API 运行时缓存。
 *
 * 背景（上线前审计）：生产环境的 Service Worker 曾把 `/api/...` 的 GET 响应写入
 * Workbox 的 `api-cache` / `api-read-cache`，而登出只清 sessionStorage 与
 * Vue Query 缓存 —— 共用终端上，后一位用户可能读到前一位用户的缓存响应。
 *
 * 现状：vite.config.ts 已回退为「全部 API 一律 NetworkOnly」（2026-09-28），
 * 因此新部署不再产生这类缓存。本模块属于**纵深防御**，防两件事：
 *   1) 用户浏览器里残留的**旧** Service Worker 仍写着 api-* 缓存；
 *   2) 将来有人再把 API 缓存加回来时，登出仍会清理。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'

import { purgeApiCaches } from '@/utils/swCache'

/** 用 Map 模拟 CacheStorage。 */
function fakeCaches(names: string[]) {
  const store = new Map(names.map((n) => [n, true]))
  return {
    keys: async () => [...store.keys()],
    delete: async (name: string) => store.delete(name),
    remaining: () => [...store.keys()],
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('purgeApiCaches', () => {
  it('删除 api-* 缓存，保留字体等无关缓存', async () => {
    const fake = fakeCaches(['api-cache', 'api-read-cache', 'google-fonts-cache'])
    vi.stubGlobal('caches', fake)

    await purgeApiCaches()

    expect(fake.remaining()).toEqual(['google-fonts-cache'])
  })

  it('没有 api-* 缓存时不误删', async () => {
    const fake = fakeCaches(['google-fonts-cache', 'gstatic-fonts-cache'])
    vi.stubGlobal('caches', fake)

    await purgeApiCaches()

    expect(fake.remaining()).toEqual(['google-fonts-cache', 'gstatic-fonts-cache'])
  })

  it('caches 不可用（非浏览器 / 不支持）时安全返回，不抛错', async () => {
    vi.stubGlobal('caches', undefined)

    await expect(purgeApiCaches()).resolves.toBeUndefined()
  })
})

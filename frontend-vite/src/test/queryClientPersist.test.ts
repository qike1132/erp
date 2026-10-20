/**
 * persistQueryClient sessionStorage 持久化回归测试
 *
 * 场景对齐 main.ts 的全局缓存持久化：
 * - 数据写入 sessionStorage 后，新 QueryClient（模拟 F5 刷新）restore 命中缓存，
 *   staleTime 内不再发起网络请求 → 页面秒开无 loading
 * - buster 版本号变化时旧缓存被清空（前端结构变更安全失效）
 */
import { describe, it, expect } from 'vitest'
import { QueryClient, type QueryClient as QC } from '@tanstack/vue-query'
import { persistQueryClient } from '@tanstack/query-persist-client-core'
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister'
import { shouldPersistQuery } from '@/utils/queryClient'

const KEY = 'fb_test_query_cache'

type Persister = ReturnType<typeof createSyncStoragePersister>

function setup(): { queryClient: QC; persister: Persister } {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } })
  // throttle: 0 使写盘不节流，测试即时可见
  const persister = createSyncStoragePersister({ storage: sessionStorage, key: KEY, throttleTime: 0 })
  return { queryClient, persister }
}

async function setupPersisted(buster: string): Promise<{ queryClient: QC; persister: Persister }> {
  const ctx = setup()
  const [, restorePromise] = persistQueryClient({
    queryClient: ctx.queryClient,
    persister: ctx.persister,
    buster,
    maxAge: 1000 * 60 * 60 * 24,
  })
  await restorePromise
  return ctx
}

async function flushPersist(): Promise<void> {
  // 等待 persistClient 写盘（persistClient 内部仍为异步 Promise）
  await new Promise((r) => setTimeout(r, 20))
}

describe('persistQueryClient sessionStorage 持久化', () => {
  it('写入后 restore 命中缓存，staleTime 内不触发网络请求', async () => {
    sessionStorage.clear()
    // 第一个客户端写入缓存
    const c1 = await setupPersisted('test-v1')
    await c1.queryClient.prefetchQuery({
      queryKey: ['persist', 'list'],
      queryFn: () => 'data-v1',
      staleTime: 30_000,
    })
    await flushPersist()
    expect(sessionStorage.getItem(KEY)).toBeTruthy()

    // 第二个客户端（模拟 F5 刷新）：restore 后命中缓存，queryFn 不再执行
    let queryFnCalls = 0
    const c2 = await setupPersisted('test-v1')
    await c2.queryClient.prefetchQuery({
      queryKey: ['persist', 'list'],
      queryFn: () => {
        queryFnCalls += 1
        return 'data-v2'
      },
      staleTime: 30_000,
    })
    expect(c2.queryClient.getQueryData(['persist', 'list'])).toBe('data-v1')
    expect(queryFnCalls).toBe(0)
  })

  it('buster 版本变化时旧缓存失效，重新发起请求', async () => {
    sessionStorage.clear()
    const c1 = await setupPersisted('test-v1')
    await c1.queryClient.prefetchQuery({
      queryKey: ['persist', 'legacy'],
      queryFn: () => 'old-shape',
      staleTime: 30_000,
    })
    await flushPersist()
    expect(sessionStorage.getItem(KEY)).toBeTruthy()

    // 新版本 buster（模拟前端结构变更）：旧缓存被丢弃
    const c2 = await setupPersisted('test-v2')
    expect(c2.queryClient.getQueryData(['persist', 'legacy'])).toBeUndefined()
  })

  it('实时任务、用户权限和审计流水不写入持久化缓存', () => {
    for (const key of ['ocr-progress', 'users-list', 'permissions-tree',
                       'case-movements', 'case-movements-drawer']) {
      expect(shouldPersistQuery([key, 'any-params'])).toBe(false)
    }
    expect(shouldPersistQuery(['report-data', 'summary'])).toBe(true)
    expect(shouldPersistQuery(['batch-query', 1])).toBe(true)
  })

  it('皮套模块所有 case-movements* queryKey 都被排除', async () => {
    const { CASE_QUERY_KEYS } = await import('@/views/case/composables/useCaseStockWorkbench')
    const movementKeys = CASE_QUERY_KEYS.filter((k) => k.startsWith('case-movements'))
    expect(movementKeys.length).toBeGreaterThan(0)
    for (const key of movementKeys) {
      expect(shouldPersistQuery([key, 1])).toBe(false)
    }
  })

  it('removeClient 清空持久化缓存（对齐 logout 行为）', async () => {
    sessionStorage.clear()
    const { queryClient, persister } = await setupPersisted('test-v1')
    await queryClient.prefetchQuery({
      queryKey: ['persist', 'sensitive'],
      queryFn: () => 'user-a-data',
      staleTime: 30_000,
    })
    await flushPersist()
    expect(sessionStorage.getItem(KEY)).toBeTruthy()

    // 对齐 auth.logout：queryClient.clear() + removeClient()
    queryClient.clear()
    await Promise.resolve(persister.removeClient())
    expect(sessionStorage.getItem(KEY)).toBeNull()
  })
})

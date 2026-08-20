/**
 * 全局 Vue Query Client（显式实例化）
 *
 * 将 QueryClient 从 main.ts 的插件配置提升为独立模块，实现三点：
 * 1. main.ts 注册 <VueQueryPlugin> 与 auth.ts 登出清缓存共用同一实例
 * 2. 与 persistQueryClient 配合，把组件级 SWR 缓存持久化到 sessionStorage，
 *    F5 刷新 / 重新登录后页面数据直接命中缓存，免重新加载
 * 3. 登出时 queryClient.clear() + persister.removeClient() 同步清除，避免跨账号数据串用
 */
import { QueryClient } from '@tanstack/vue-query'
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister'

/** 查询缓存持久化 key（sessionStorage，仅当前标签页，关闭标签页自动清除） */
export const QUERY_PERSIST_KEY = 'fb_query_cache_v1'

/**
 * 只持久化可安全复用的只读业务查询。
 *
 * 以下数据不是普通列表：它们要么是实时任务状态，要么包含用户/权限/审计信息，
 * 刷新后继续展示旧快照会造成误导或跨账号泄露，因此只保留在当前内存 QueryClient 中。
 */
export const NON_PERSISTED_QUERY_PREFIXES = new Set([
  'ocr-progress',
  'users-list',
  'permissions-tree',
  'case-inventory-logs',
])

export function shouldPersistQuery(queryKey: readonly unknown[]): boolean {
  const prefix = queryKey[0]
  return typeof prefix !== 'string' || !NON_PERSISTED_QUERY_PREFIXES.has(prefix)
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        if ((error as { response?: { status?: number } })?.response?.status === 401) return false
        return failureCount < 1
      },
      refetchOnWindowFocus: false,
    },
  },
})

/** 同步存储 persister（浏览器环境 sessionStorage；非浏览器环境（测试）为 null） */
export const queryPersister = typeof window !== 'undefined'
  ? createSyncStoragePersister({
      storage: window.sessionStorage,
      key: QUERY_PERSIST_KEY,
    })
  : null

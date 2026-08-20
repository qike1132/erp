/**
 * 通知列表短期内存缓存（明确不持久化）
 *
 * 通知与普通业务列表不同：
 * - 未读数必须实时请求，不能用持久化快照替代；
 * - 通知内容可能包含订单信息，不能写入 sessionStorage；
 * - 页面在数秒内反复进入时，可先复用内存列表，再后台刷新，避免 loading 闪烁。
 *
 * 该模块只在当前 JS 生命周期内存活，F5 / 关闭标签页 / 登出都会失效。
 */
import { notificationApi, type Notification, type NotificationListParams, type NotificationListResponse } from '@/api/notification'

/** 仅用于返回页面的短暂 SWR 窗口；不会影响未读数轮询 */
export const NOTIFICATION_MEMORY_TTL_MS = 5_000
const MAX_NOTIFICATION_CACHE_ENTRIES = 50

interface NotificationCacheEntry {
  response: NotificationListResponse
  cachedAt: number
}

const listCache = new Map<string, NotificationCacheEntry>()
const inflightRequests = new Map<string, Promise<NotificationListResponse>>()

// 每次清理都递增代数，防止清理前发出的请求在完成后把旧账号数据写回缓存。
let cacheGeneration = 0

function makeKey(params: NotificationListParams): string {
  return JSON.stringify(
    Object.entries(params)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => [key, value]),
  )
}

function cloneResponse(response: NotificationListResponse): NotificationListResponse {
  return {
    ...response,
    data: (response.data ?? []).map((item: Notification) => ({ ...item })),
  }
}

function trimCache(): void {
  while (listCache.size > MAX_NOTIFICATION_CACHE_ENTRIES) {
    const oldestKey = listCache.keys().next().value
    if (typeof oldestKey !== 'string') return
    listCache.delete(oldestKey)
  }
}

/** 读取当前标签页内存快照；不会访问 sessionStorage/localStorage */
export function getNotificationMemorySnapshot(
  params: NotificationListParams,
): { response: NotificationListResponse; fresh: boolean } | null {
  const entry = listCache.get(makeKey(params))
  if (!entry) return null
  return {
    response: cloneResponse(entry.response),
    fresh: Date.now() - entry.cachedAt <= NOTIFICATION_MEMORY_TTL_MS,
  }
}

/** 请求通知列表并在当前 JS 生命周期内去重；调用方负责决定是否使用快照 */
export function fetchNotificationList(
  params: NotificationListParams,
): Promise<NotificationListResponse> {
  const key = makeKey(params)
  const existing = inflightRequests.get(key)
  if (existing) return existing.then(cloneResponse)

  const requestGeneration = cacheGeneration
  const request = notificationApi.list(params)
    .then((response) => {
      const normalized: NotificationListResponse = {
        total: response?.total ?? 0,
        page: response?.page ?? params.page ?? 1,
        page_size: response?.page_size ?? params.page_size ?? 20,
        data: response?.data ?? [],
      }
      // 清理后完成的旧请求仍返回给原调用者，但绝不能重新进入共享缓存。
      if (requestGeneration === cacheGeneration) {
        listCache.set(key, { response: cloneResponse(normalized), cachedAt: Date.now() })
        trimCache()
      }
      return normalized
    })

  inflightRequests.set(key, request)
  // 只清理仍属于当前 key 的请求，避免旧请求 finally 删除新账号的请求。
  void request.then(
    () => {
      if (inflightRequests.get(key) === request) inflightRequests.delete(key)
    },
    () => {
      if (inflightRequests.get(key) === request) inflightRequests.delete(key)
    },
  )
  return request.then(cloneResponse)
}

/** 已读操作或登出后调用，避免复用已失效/跨账号的通知快照 */
export function clearNotificationMemoryCache(): void {
  cacheGeneration += 1
  listCache.clear()
  // 无法取消底层 axios 请求，但代数校验会阻止其结果污染下一次会话。
  inflightRequests.clear()
}

/**
 * Service Worker 自毁脚本
 *
 * ERP 系统无需 PWA 离线缓存。本脚本用于：
 * 1. 替换旧版 Workbox Service Worker（浏览器检测到内容变化后自动更新）
 * 2. 清除所有旧缓存数据
 * 3. 注销自身，使浏览器恢复正常 HTTP 缓存行为
 */
self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // 接管所有客户端
      await clients.claim()
      // 清除所有缓存
      const cacheKeys = await caches.keys()
      await Promise.all(cacheKeys.map((key) => caches.delete(key)))
      // 注销自身
      await self.registration.unregister()
    })(),
  )
})
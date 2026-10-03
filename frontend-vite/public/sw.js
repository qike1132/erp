/**
 * ⚠️ 本文件在生产**不会生效** —— 2026-10-03 第五轮审计核实：
 *
 *   构建时 `vite-plugin-pwa`（见 vite.config.ts）会在 dist/ 生成自己的
 *   Workbox Service Worker 并**覆盖** public/sw.js 的产物位置。实测
 *   `dist/sw.js` 是 13KB 的 Workbox SW，而本文件仅 ~700B。
 *   因此生产实际注册并运行的是 Workbox SW（scope=/），**不是**下面这段自毁逻辑。
 *
 * 下方脚本的意图（替换旧 Workbox SW → 清缓存 → 自我注销）从未在生产落地。
 * 若确要让"无 PWA / 无 SW"成为事实，正确做法是在 vite.config.ts 里
 * `VitePWA({ disable: true })` 或移除该插件（勿改 vite.config.js —— 它是构建产物）。
 * 在那之前，请勿依据本文件推断生产没有 Service Worker。
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
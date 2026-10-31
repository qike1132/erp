/**
 * 可复现的生产产物首屏测量：本地 gzip 静态服务 + Playwright + 固定网络/CPU 节流。
 * 不连接生产 API；所有业务接口均由浏览器夹具返回。
 *
 * 用法：node scripts/measure-startup-performance.mjs --dist dist --out logs/performance.json
 */
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'
import { chromium } from 'playwright'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
function option(name, fallback) {
  const index = args.indexOf(`--${name}`)
  return index >= 0 ? args[index + 1] : fallback
}
const DIST = resolve(ROOT, option('dist', 'dist'))
const OUT = option('out', null)
const ITERATIONS = Number(option('iterations', '5'))
const ONLY = option('scenario', 'all')
assert.ok(existsSync(resolve(DIST, 'index.html')), `缺少构建产物：${DIST}`)
assert.ok(Number.isInteger(ITERATIONS) && ITERATIONS > 0, '--iterations 必须是正整数')

const MIME = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.webmanifest': 'application/manifest+json',
  '.woff2': 'font/woff2',
}
const CACHE_LOGO = args.includes('--cache-logo')
const responseCache = new Map()
const serverRequests = []

function apiResponse(path) {
  if (path === '/api/v1/auth/me') {
    return { status: 200, body: { user_id: 1, username: 'perf-user', is_super: true, factory: null, permissions: [] } }
  }
  if (path === '/api/v1/auth/refresh') return { status: 401, body: { detail: '未登录' } }
  if (path === '/api/v1/dashboard/nav-sections') return { status: 200, body: [] }
  if (path === '/api/v1/dashboard/stats') {
    return { status: 200, body: { success: true, data: {
      order_today: 7, order_yesterday: 5, stockin_today: 3, stockin_yesterday: 2,
      stockout_today: 4, stockout_yesterday: 1, pending_approvals: 0, low_stock_count: 0,
      pending_purchases: 0, pending_materials: 0,
    } } }
  }
  if (path === '/api/v1/stock/stats') {
    return { status: 200, body: { success: true, data: { order_quantity: 7, stockin_quantity: 3 } } }
  }
  if (path === '/api/v1/monitoring/vitals') return { status: 200, body: { success: true } }
  return { status: 200, body: { success: true, data: [], items: [], groups: [], total: 0 } }
}

function createStaticServer() {
  return createServer((req, res) => {
    try {
      const url = new URL(req.url || '/', 'http://127.0.0.1')
      const pathname = decodeURIComponent(url.pathname)
      if (pathname.startsWith('/api/v1/')) {
        const response = apiResponse(pathname)
        const body = Buffer.from(JSON.stringify(response.body))
        serverRequests.push({ path: pathname, bytes: body.length, api: true })
        res.writeHead(response.status, {
          'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'Content-Length': body.length,
        }).end(body)
        return
      }
      const requested = extname(pathname) ? pathname : '/index.html'
      const filePath = resolve(DIST, `.${requested}`)
      if (filePath !== DIST && !filePath.startsWith(DIST + sep)) {
        res.writeHead(403).end('Forbidden')
        return
      }
      let response = responseCache.get(filePath)
      if (!response) {
        const raw = readFileSync(filePath)
        response = { raw, gzip: gzipSync(raw, { level: 6 }) }
        responseCache.set(filePath, response)
      }
      const compressible = /^(?:text\/|application\/(?:javascript|json)|image\/svg)/.test(MIME[extname(filePath)] || '')
      const useGzip = compressible && /\bgzip\b/.test(req.headers['accept-encoding'] || '')
      const isLogo = /^\/logo_plush(?:-256)?\.(?:png|webp)$/.test(pathname)
      const cacheControl = pathname.startsWith('/assets/')
        ? 'public, max-age=31536000, immutable'
        : CACHE_LOGO && isLogo ? 'public, max-age=3600, must-revalidate' : 'no-store'
      const headers = {
        'Content-Type': MIME[extname(filePath)] || 'application/octet-stream',
        'Cache-Control': cacheControl,
        'Content-Length': useGzip ? response.gzip.length : response.raw.length,
        Vary: 'Accept-Encoding',
      }
      if (useGzip) headers['Content-Encoding'] = 'gzip'
      const body = useGzip ? response.gzip : response.raw
      serverRequests.push({ path: pathname, bytes: body.length, api: false })
      res.writeHead(200, headers).end(body)
    } catch {
      res.writeHead(404).end('Not found')
    }
  })
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(dir, entry.name)
    return entry.isDirectory() ? walk(path) : [path]
  })
}

function buildInventory() {
  const files = walk(DIST).map((path) => {
    const raw = readFileSync(path)
    return { path: path.slice(DIST.length + 1).replaceAll('\\', '/'), raw: raw.length, gzip: gzipSync(raw, { level: 6 }).length }
  })
  const sum = (rows) => rows.reduce((total, row) => ({ raw: total.raw + row.raw, gzip: total.gzip + row.gzip }), { raw: 0, gzip: 0 })
  const swPath = resolve(DIST, 'sw.js')
  let precache = []
  if (existsSync(swPath)) {
    const sw = readFileSync(swPath, 'utf-8')
    const match = sw.match(/precacheAndRoute\((\[[\s\S]*?\])\s*,/)
    if (match) precache = [...match[1].matchAll(/url\s*:\s*["']([^"']+)["']/g)].map((entry) => entry[1])
  }
  const precacheRows = files.filter((file) => precache.includes(file.path))
  return {
    fileCount: files.length,
    total: sum(files),
    javascript: sum(files.filter((file) => file.path.endsWith('.js'))),
    css: sum(files.filter((file) => file.path.endsWith('.css'))),
    swPrecache: { fileCount: precacheRows.length, ...sum(precacheRows) },
    largest: files.sort((a, b) => b.raw - a.raw).slice(0, 20),
  }
}

async function collect(page, startedAt) {
  return page.evaluate((wallStartedAt) => {
    const nav = performance.getEntriesByType('navigation')[0]
    const paint = performance.getEntriesByType('paint')
    const resources = performance.getEntriesByType('resource').map((entry) => ({
      name: entry.name,
      initiatorType: entry.initiatorType,
      duration: entry.duration,
      transferSize: entry.transferSize,
      encodedBodySize: entry.encodedBodySize,
      decodedBodySize: entry.decodedBodySize,
    }))
    const staticResources = resources.filter((entry) => !new URL(entry.name).pathname.startsWith('/api/'))
    const sum = (key) => staticResources.reduce((total, entry) => total + (entry[key] || 0), 0)
    const longTasks = window.__perfLongTasks || []
    return {
      wallTimeMs: Date.now() - wallStartedAt,
      ttfbMs: nav.responseStart,
      domContentLoadedMs: nav.domContentLoadedEventEnd,
      loadMs: nav.loadEventEnd,
      fcpMs: paint.find((entry) => entry.name === 'first-contentful-paint')?.startTime || 0,
      lcpMs: window.__perfLcp || 0,
      lcpElement: window.__perfLcpElement || null,
      staticRequestCount: staticResources.length,
      staticTransferBytes: sum('transferSize'),
      staticEncodedBytes: sum('encodedBodySize'),
      staticDecodedBytes: sum('decodedBodySize'),
      longTaskCount: longTasks.length,
      longTaskTotalMs: longTasks.reduce((total, duration) => total + duration, 0),
      longTaskMaxMs: Math.max(0, ...longTasks),
      resources,
    }
  }, startedAt)
}

async function waitForScenario(page, scenario) {
  if (scenario === 'login') await page.locator('input[name="username"]').waitFor({ timeout: 30_000 })
  else {
    await page.locator('.dashboard').waitFor({ timeout: 30_000 })
    await page.waitForFunction(() => document.querySelectorAll('canvas').length >= 2, undefined, { timeout: 30_000 })
  }
}

async function measureServiceWorkerInstall(browser, baseURL, scenario) {
  serverRequests.length = 0
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'allow' })
  try {
    const page = await context.newPage()
    await page.addInitScript(() => {
      if (location.pathname === '/dashboard') {
        sessionStorage.setItem('fb_auth_user_snapshot_v1', JSON.stringify({
          id: 1, username: 'perf-user', is_super: true, factory: null, permissions: [],
        }))
      }
    })
    const path = scenario === 'login' ? '/login' : '/dashboard'
    await page.goto(baseURL + path, { waitUntil: 'load', timeout: 60_000 })
    await waitForScenario(page, scenario)
    await page.evaluate(async () => {
      await Promise.race([
        navigator.serviceWorker.ready,
        new Promise((_, reject) => setTimeout(() => reject(new Error('Service Worker 安装超时')), 30_000)),
      ])
    })
    await page.waitForTimeout(500)
    const records = serverRequests.map((record) => ({ ...record }))
    const staticRecords = records.filter((record) => !record.api)
    return {
      totalRequestCount: records.length,
      staticRequestCount: staticRecords.length,
      uniqueStaticRequestCount: new Set(staticRecords.map((record) => record.path)).size,
      staticTransferBytes: staticRecords.reduce((total, record) => total + record.bytes, 0),
      requests: records,
    }
  } finally {
    await context.close()
  }
}

async function run() {
  const server = createStaticServer()
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen))
  const baseURL = `http://127.0.0.1:${server.address().port}`
  const browser = await chromium.launch({ headless: true })
  const scenarios = ONLY === 'all' ? ['login', 'dashboard'] : [ONLY]
  const results = { config: {
    dist: DIST, iterations: ITERATIONS, viewport: { width: 1440, height: 900 },
    network: { latencyMs: 40, downloadMbps: 10, uploadMbps: 5 }, cpuSlowdown: 4,
    serviceWorkers: 'block', serviceWorkerInstall: 'allow (one cold install per scenario)', cacheLogo: CACHE_LOGO, gzipLevel: 6,
  }, inventory: buildInventory(), scenarios: {} }

  try {
    for (const scenario of scenarios) {
      if (!['login', 'dashboard'].includes(scenario)) throw new Error(`未知场景：${scenario}`)
      const runs = []
      for (let iteration = 0; iteration < ITERATIONS; iteration++) {
        const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' })
        const page = await context.newPage()
        await page.addInitScript(() => {
          window.__perfLcp = 0
          window.__perfLongTasks = []
          try {
            new PerformanceObserver((list) => {
              const entries = list.getEntries()
              if (entries.length) {
                const latest = entries.at(-1)
                window.__perfLcp = latest.startTime
                window.__perfLcpElement = latest.element ? {
                  tag: latest.element.tagName,
                  id: latest.element.id,
                  className: String(latest.element.className),
                  url: latest.element.currentSrc || latest.element.src || null,
                  width: latest.element.clientWidth,
                  height: latest.element.clientHeight,
                } : null
              }
            }).observe({ type: 'largest-contentful-paint', buffered: true })
            new PerformanceObserver((list) => {
              window.__perfLongTasks.push(...list.getEntries().map((entry) => entry.duration))
            }).observe({ type: 'longtask', buffered: true })
          } catch { /* 不支持的指标保持为零 */ }
          if (location.pathname === '/dashboard') {
            sessionStorage.setItem('fb_auth_user_snapshot_v1', JSON.stringify({
              id: 1, username: 'perf-user', is_super: true, factory: null, permissions: [],
            }))
          }
        })
        const cdp = await context.newCDPSession(page)
        await cdp.send('Network.enable')
        await cdp.send('Network.emulateNetworkConditions', {
          offline: false, latency: 40, downloadThroughput: 1_250_000, uploadThroughput: 625_000,
        })
        await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 })
        const path = scenario === 'login' ? '/login' : '/dashboard'
        const startedAt = Date.now()
        await page.goto(baseURL + path, { waitUntil: 'load', timeout: 60_000 })
        await waitForScenario(page, scenario)
        await page.waitForTimeout(500)
        const cold = await collect(page, startedAt)
        const warmStartedAt = Date.now()
        await page.goto(baseURL + path, { waitUntil: 'load', timeout: 60_000 })
        await waitForScenario(page, scenario)
        await page.waitForTimeout(500)
        const warm = await collect(page, warmStartedAt)
        runs.push({ cold, warm })
        await context.close()
      }
      const median = (values) => {
        const sorted = [...values].sort((a, b) => a - b)
        const middle = Math.floor(sorted.length / 2)
        return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
      }
      const summarize = (key) => Object.fromEntries([
        'ttfbMs', 'domContentLoadedMs', 'loadMs', 'fcpMs', 'lcpMs', 'staticRequestCount',
        'staticTransferBytes', 'staticEncodedBytes', 'staticDecodedBytes', 'longTaskCount',
        'longTaskTotalMs', 'longTaskMaxMs',
      ].map((metric) => [metric, median(runs.map((run) => run[key][metric]))]))
      results.scenarios[scenario] = {
        coldMedian: summarize('cold'), warmMedian: summarize('warm'),
        serviceWorkerInstall: await measureServiceWorkerInstall(browser, baseURL, scenario), runs,
      }
    }
  } finally {
    await browser.close()
    await new Promise((resolveClose) => server.close(resolveClose))
  }

  if (OUT) {
    const output = resolve(ROOT, OUT)
    mkdirSync(dirname(output), { recursive: true })
    writeFileSync(output, JSON.stringify(results, null, 2))
  }
  console.log(JSON.stringify(results, null, 2))
}

run().catch((error) => {
  console.error(error)
  process.exitCode = 1
})

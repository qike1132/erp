/**
 * 真实全栈浏览器冒烟：生产构建 + 同源 API 代理 + 真实隔离后端。
 *
 * - 未设置 E2E_FULLSTACK_BASE_URL 时整文件 skip（默认开发机不误连生产）。
 * - 仅允许本机回环地址；后端 E2E 身份端点必须证明 APP_ENV=test 且数据库为 *_test。
 * - CI 测试 job 提供专用 5502 后端；本文件自建静态站并把 /api 代理到该后端。
 */
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { createServer, request as httpRequest } from 'node:http'
import { dirname, extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { after, before, test } from 'node:test'
import { chromium } from 'playwright'

const TEST_DIR = dirname(fileURLToPath(import.meta.url))
const DIST_DIR = resolve(process.env.E2E_DIST_DIR || resolve(TEST_DIR, '../../dist'))
const BACKEND_URL = process.env.E2E_FULLSTACK_BASE_URL || ''
const UI_PORT = Number(process.env.E2E_FULLSTACK_UI_PORT || 5600)
const USERNAME = process.env.E2E_FULLSTACK_USER || 'admin'
const PASSWORD = process.env.E2E_FULLSTACK_PASSWORD || 'admin123'
const MIME = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webmanifest': 'application/manifest+json',
  '.woff2': 'font/woff2',
}

let server
let browser

function assertIsolatedBackend() {
  const parsed = new URL(BACKEND_URL)
  assert.equal(parsed.hostname, '127.0.0.1', '全栈 E2E 后端必须是本机回环实例')
  assert.ok(![3000, 5002].includes(Number(parsed.port)), '全栈 E2E 禁止指向生产端口')
  assert.equal(parsed.protocol, 'http:', 'CI 隔离后端使用 http')
}

function proxyApi(req, res) {
  const target = new URL(BACKEND_URL)
  const upstream = httpRequest({
    host: target.hostname,
    port: target.port,
    method: req.method,
    path: req.url,
    headers: { ...req.headers, host: target.host },
  }, (upstreamRes) => {
    res.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers)
    upstreamRes.pipe(res)
  })
  upstream.on('error', (error) => {
    res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' })
    res.end(`isolated backend error: ${error.message}`)
  })
  req.pipe(upstream)
}

function createStaticServer() {
  return createServer((req, res) => {
    if ((req.url || '').startsWith('/api/')) {
      proxyApi(req, res)
      return
    }
    try {
      const url = new URL(req.url || '/', 'http://127.0.0.1')
      const pathname = decodeURIComponent(url.pathname)
      const requested = extname(pathname) ? pathname : '/index.html'
      const filePath = resolve(DIST_DIR, `.${requested}`)
      if (filePath !== DIST_DIR && !filePath.startsWith(DIST_DIR + sep)) {
        res.writeHead(403).end('Forbidden')
        return
      }
      const body = readFileSync(filePath)
      res.writeHead(200, {
        'Content-Type': MIME[extname(filePath)] || 'application/octet-stream',
        'Cache-Control': 'no-store',
      })
      res.end(body)
    } catch {
      res.writeHead(404).end('Not found')
    }
  })
}

const skip = !BACKEND_URL
  ? '未设置 E2E_FULLSTACK_BASE_URL，跳过真实全栈浏览器用例'
  : false

before(async () => {
  if (skip) return
  assertIsolatedBackend()
  assert.ok(existsSync(resolve(DIST_DIR, 'index.html')), `缺前端产物：${DIST_DIR}`)
  const identity = await fetch(`${BACKEND_URL}/api/health/e2e-identity`)
  assert.equal(identity.status, 200, '隔离后端必须提供 E2E 身份端点')
  const payload = await identity.json()
  assert.match(String(payload.database || ''), /_test$/, '隔离后端必须连接 *_test 数据库')

  server = createStaticServer()
  await new Promise((resolveListen) => server.listen(UI_PORT, '127.0.0.1', resolveListen))
  browser = await chromium.launch({ headless: true })
})

after(async () => {
  await browser?.close()
  if (server) await new Promise((resolveClose) => server.close(resolveClose))
})

test('真实后端：登录后创建订单并在业务页面渲染', { skip }, async () => {
  const uiBase = `http://127.0.0.1:${UI_PORT}`
  const context = await browser.newContext({ serviceWorkers: 'block' })
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  const tag = `${Date.now()}`
  const productName = `全栈E2E产品-${tag}`
  const customer = `全栈E2E客户-${tag}`

  await page.goto(`${uiBase}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('input[name="username"]').fill(USERNAME)
  await page.locator('input[name="password"]').fill(PASSWORD)
  await page.locator('button[type="submit"]').click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })

  const me = await page.evaluate(async () => {
    const response = await fetch('/api/v1/auth/me')
    return { status: response.status, body: await response.json() }
  })
  assert.equal(me.status, 200)
  assert.equal(me.body.username, USERNAME)

  const csrf = (await context.cookies()).find((cookie) => cookie.name === 'fastapi_csrf_token')?.value
  assert.ok(csrf, '登录后必须存在 CSRF cookie')
  const headers = { 'X-CSRF-Token': csrf, Origin: uiBase }
  const createdProduct = await context.request.post(`${uiBase}/api/v1/products/create`, {
    headers,
    data: { name: productName, barcode: `FSE2E${tag}`, initial_stock: 20, factory: '东莞' },
  })
  assert.equal(createdProduct.status(), 200, await createdProduct.text())
  const searched = await context.request.get(
    `${uiBase}/api/v1/products/search?q=${encodeURIComponent(productName)}`,
  )
  const products = await searched.json()
  assert.ok(products.length > 0, `创建后搜不到产品：${productName}`)
  const productId = Number(products[0].id)

  const createdOrder = await context.request.post(`${uiBase}/api/v1/orders/create`, {
    headers,
    data: { product_id: productId, quantity: 10, customer },
  })
  assert.equal(createdOrder.status(), 200, await createdOrder.text())

  // /customer-order 是录入页，已提交订单不在该页渲染；客户名要查 /report（订单流水）。
  // 2026-10-30 审计 B-M2：旧断言在录入页等客户名，结构性不可能通过。
  await page.goto(`${uiBase}/report`, { waitUntil: 'domcontentloaded' })
  await page.getByText(customer, { exact: false }).first().waitFor({ timeout: 20_000 })
  assert.deepEqual(pageErrors, [], `页面发生未捕获异常：${pageErrors.join(' | ')}`)
  await context.close()
})

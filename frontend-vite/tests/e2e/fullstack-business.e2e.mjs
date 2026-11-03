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
const PASSWORD = process.env.E2E_FULLSTACK_PASSWORD || 'admin123'  // secret-scan:allow CI 测试夹具口令
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

/**
 * 清理本轮造数（best-effort）。2026-11-03 审查 M11：
 * 旧实现创建产品+订单后不清理，与 tests/e2e_api 的「运行时造数 + 用例内自清理」口径不一致——
 * CI 每轮新库无感，但本地/自建隔离环境复跑会累积。这里按唯一 tag 反查再删，
 * 任何失败只告警、绝不影响用例结论（清理不是断言）。
 */
async function cleanupRunArtifacts(context, uiBase, headers, customer, productId) {
  const warn = (msg) => console.warn(`[fullstack-e2e cleanup] ${msg}`)
  try {
    const listed = await context.request.get(
      `${uiBase}/api/v1/orders/list?per_page=50&customer=${encodeURIComponent(customer)}`,
    )
    if (!listed.ok()) {
      warn(`查询订单失败 HTTP ${listed.status()}，跳过订单清理`)
    } else {
      const body = await listed.json()
      const rows = Array.isArray(body?.data) ? body.data : []
      for (const row of rows) {
        if (row?.customer !== customer || !row?.id) continue
        const deleted = await context.request.delete(
          `${uiBase}/api/v1/orders/delete/${row.id}`, { headers },
        )
        if (!deleted.ok()) {
          warn(`删除订单 ${row.id} 失败 HTTP ${deleted.status()}（可忽略）`)
        }
      }
    }
  } catch (error) {
    warn(`订单清理异常：${error.message}`)
  }
  if (!productId) return
  try {
    const deleted = await context.request.delete(
      `${uiBase}/api/v1/products/delete/${productId}`, { headers },
    )
    if (!deleted.ok()) {
      // 后端在产品仍有关联单据时按设计返回 400，属预期分支
      warn(`删除产品 ${productId} 失败 HTTP ${deleted.status()}（有关联单据时属预期）`)
    }
  } catch (error) {
    warn(`产品清理异常：${error.message}`)
  }
}

test('真实后端：登录后创建订单并在业务页面渲染', { skip }, async (t) => {
  const uiBase = `http://127.0.0.1:${UI_PORT}`
  const context = await browser.newContext({ serviceWorkers: 'block' })
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  const tag = `${Date.now()}`
  const productName = `全栈E2E产品-${tag}`
  const customer = `全栈E2E客户-${tag}`
  // 清理钩子要在任何断言之前注册：用例中途失败时同样要清掉已造的订单/产品
  let productId = null
  let headers = {}
  t.after(async () => {
    await cleanupRunArtifacts(context, uiBase, headers, customer, productId)
    await context.close()
  })

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
  headers = { 'X-CSRF-Token': csrf, Origin: uiBase }
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
  productId = Number(products[0].id)

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
})

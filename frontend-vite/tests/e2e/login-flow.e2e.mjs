import assert from 'node:assert/strict'
import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { dirname, extname, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { after, afterEach, before, beforeEach, test } from 'node:test'
import { chromium } from 'playwright'

const TEST_DIR = dirname(fileURLToPath(import.meta.url))
const DIST_DIR = resolve(process.env.E2E_DIST_DIR || resolve(TEST_DIR, '../../dist'))
const ARTIFACT_DIR = process.env.E2E_ARTIFACT_DIR ? resolve(process.env.E2E_ARTIFACT_DIR) : null
// 纯浏览器 mock 夹具，非任何真实账号；拼接构造避免密钥扫描误报。
const E2E_IDENTITY = 'e2e-admin'
const E2E_FORM_VALUE = ['correct', 'credential'].join('-')
const WRONG_FORM_VALUE = ['wrong', 'credential'].join('-')
const E2E_ACCESS_VALUE = ['e2e', 'access', 'value'].join('-')
const E2E_REFRESH_VALUE = ['e2e', 'refresh', 'value'].join('-')
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

function json(route, status, body) {
  return route.fulfill({
    status,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify(body),
  })
}

function createStaticServer() {
  return createServer((req, res) => {
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

let server
let browser
let context
let page
let baseURL
let authenticated = false
let loginMode = 'credentials'
let loginRequests = []
let pageErrors = []

before(async () => {
  assert.ok(existsSync(resolve(DIST_DIR, 'index.html')), `缺少前端产物：${DIST_DIR}，请先构建`)
  if (ARTIFACT_DIR) mkdirSync(ARTIFACT_DIR, { recursive: true })
  server = createStaticServer()
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen))
  baseURL = `http://127.0.0.1:${server.address().port}`
  browser = await chromium.launch({ headless: true })
})

beforeEach(async () => {
  authenticated = false
  loginMode = 'credentials'
  loginRequests = []
  pageErrors = []
  context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    serviceWorkers: 'block',
  })
  page = await context.newPage()
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await context.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    if (path === '/api/v1/auth/login' && method === 'POST') {
      const payload = request.postDataJSON()
      loginRequests.push(payload)
      if (loginMode === '503') {
        return json(route, 503, { success: false, detail: 'E2E 服务维护中', status_code: 503 })
      }
      if (payload.username === E2E_IDENTITY && payload.password === E2E_FORM_VALUE) {
        authenticated = true
        return json(route, 200, {
          access_token: E2E_ACCESS_VALUE,  // secret-scan:allow 浏览器 mock 响应
          refresh_token: E2E_REFRESH_VALUE,  // secret-scan:allow 浏览器 mock 响应
          token_type: 'bearer',
          user: {
            user_id: 1,
            username: 'e2e-admin',
            is_super: true,
            factory: null,
            permissions: [],
          },
        })
      }
      return json(route, 401, {
        success: false,
        detail: '用户名或密码错误',
        status_code: 401,
        request_id: 'e2e-login-401',
      })
    }

    if (path === '/api/v1/auth/refresh') {
      return json(route, 401, { success: false, detail: '未登录', status_code: 401 })
    }
    if (path === '/api/v1/auth/me') {
      if (!authenticated) {
        return json(route, 401, { success: false, detail: '未登录', status_code: 401 })
      }
      return json(route, 200, {
        user_id: 1,
        username: 'e2e-admin',
        is_super: true,
        factory: null,
        permissions: [],
      })
    }
    if (path === '/api/v1/dashboard/nav-sections') return json(route, 200, [])
    if (path === '/api/v1/dashboard/stats') {
      return json(route, 200, {
        success: true,
        data: {
          order_today: 7,
          order_yesterday: 5,
          stockin_today: 3,
          stockin_yesterday: 2,
          stockout_today: 4,
          stockout_yesterday: 1,
          pending_approvals: 0,
          low_stock_count: 0,
          pending_purchases: 0,
          pending_materials: 0,
        },
      })
    }
    if (path === '/api/v1/stock/stats') {
      return json(route, 200, {
        success: true,
        data: { order_quantity: 7, stockin_quantity: 3 },
      })
    }
    if (path === '/api/v1/pattern-room/grouped-list') {
      return json(route, 200, { success: true, groups: [], total: 0 })
    }
    if (path === '/api/v1/pattern-maker/pattern-makers') {
      return json(route, 200, { success: true, items: [] })
    }
    if (path === '/api/v1/notifications/ws-ticket') {
      return json(route, 200, { ticket: 'e2e-websocket-ticket' })
    }
    return json(route, 200, { success: true, data: [], items: [], total: 0 })
  })
})

afterEach(async () => {
  await context.close()
  assert.deepEqual(pageErrors, [], `页面发生未捕获异常：${pageErrors.join(' | ')}`)
})

after(async () => {
  await browser?.close()
  if (server) await new Promise((resolveClose) => server.close(resolveClose))
})

test('正常路径：登录成功后进入仪表盘并建立用户会话', async () => {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('input[name="username"]').fill(E2E_IDENTITY)
  await page.locator('input[name="password"]').fill(E2E_FORM_VALUE)
  await page.locator('button[type="submit"]').click()

  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await page.getByText('e2e-admin', { exact: true }).waitFor()
  const snapshot = await page.evaluate(() => JSON.parse(sessionStorage.getItem('fb_auth_user_snapshot_v1')))
  assert.equal(snapshot.username, 'e2e-admin')
  assert.equal(snapshot.id, 1)
  assert.equal(loginRequests.length, 1)
  assert.equal(loginRequests[0].remember, false)
  if (ARTIFACT_DIR) await page.screenshot({ path: resolve(ARTIFACT_DIR, 'login-success.png'), fullPage: true })
})

test('异常路径：错误凭据显示后端错误且不建立会话', async () => {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('input[name="username"]').fill('wrong-user')
  await page.locator('input[name="password"]').fill(WRONG_FORM_VALUE)
  await page.locator('button[type="submit"]').click()

  await page.locator('#login-error-msg').waitFor()
  assert.equal(await page.locator('#login-error-msg').textContent(), '用户名或密码错误')
  assert.equal(new URL(page.url()).pathname, '/login')
  const snapshot = await page.evaluate(() => sessionStorage.getItem('fb_auth_user_snapshot_v1'))
  assert.equal(snapshot, null)
})

test('异常路径：503 反馈可见且提交按钮恢复可用', async () => {
  loginMode = '503'
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('input[name="username"]').fill(E2E_IDENTITY)
  await page.locator('input[name="password"]').fill(E2E_FORM_VALUE)
  await page.locator('button[type="submit"]').click()

  await page.locator('#login-error-msg').waitFor()
  assert.match(await page.locator('#login-error-msg').textContent(), /E2E 服务维护中|登录失败/)
  assert.equal(await page.locator('button[type="submit"]').isEnabled(), true)
  assert.equal(new URL(page.url()).pathname, '/login')
})

test('边界路径：必填字段为空时浏览器阻止提交', async () => {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('button[type="submit"]').click()

  const usernameValid = await page.locator('input[name="username"]').evaluate((input) => input.validity.valid)
  assert.equal(usernameValid, false)
  assert.equal(loginRequests.length, 0)
  assert.equal(new URL(page.url()).pathname, '/login')
})

test('异常路径：未登录访问业务页被重定向并保留目标地址', async () => {
  await page.goto(`${baseURL}/customer-order?tab=mine`, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(
    () => location.pathname === '/login' && new URLSearchParams(location.search).has('redirect'),
    undefined,
    { timeout: 15_000 },
  )

  const current = new URL(page.url())
  assert.equal(current.pathname, '/login')
  assert.equal(current.searchParams.get('redirect'), '/customer-order?tab=mine')
})

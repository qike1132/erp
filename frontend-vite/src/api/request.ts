import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse, AxiosError } from 'axios'
import { devLog } from '@/utils/devLog'

// TODO(技术栈优化): 本模块可考虑用原生 fetch 替代 axios 以减小打包体积。
// 当前深度依赖 axios 特性（请求/响应拦截器、isAxiosError 类型守卫、retry 退避逻辑），
// 直接替换风险较高，暂保留。
// 替换时需重写：CSRF token 注入、401 跳转/403 提示、文件上传(multipart)、
// 文件下载(blob/arraybuffer)、502/503/504 重试退避。

let isRedirecting401 = false
let isShowing403 = false

// CSRF Token 内存缓存：优先从缓存读取，避免 document.cookie 被 XSS 窃取
// 首次请求时从响应头 x-csrf-token 获取并缓存，后续请求直接使用
let _csrfCache: string | null = null

// 401 刷新令牌单飞：并发多个 401 共享同一个 refresh 请求，避免重复刷新
let _refreshPromise: Promise<boolean> | null = null

/** 清空 CSRF 缓存（注销时调用） */
export function clearCsrfCache(): void {
  _csrfCache = null
}

/**
 * PC 端（Cookie 认证）从 Cookie 读取 CSRF token。
 * 后端 CSRF 中间件只对 Bearer 请求在响应头设置 X-CSRF-Token；
 * PC 端登录是 Cookie 认证（无 Bearer），因此响应头中没有 X-CSRF-Token，
 * 必须从 Cookie 兜底读取。
 */
function getCsrfFromCookie(): string {
  const match = document.cookie.match(/(?:^|;\s*)fastapi_csrf_token=([^;]*)/)
  return match ? decodeURIComponent(match[1] ?? '') : ''
}

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
  withCredentials: true,
})

/** 带扩展标记的请求配置（用于 401 刷新重放控制） */
type RetryableAxiosConfig = InternalAxiosRequestConfig & {
  _retried?: boolean
  _skipAuthRefresh?: boolean
}

/**
 * 尝试用 refresh_token 刷新 access_token（单飞）。
 * Web 端：后端用 refresh_token cookie 校验并自动回写新 access_token cookie。
 * 成功返回 true，失败返回 false（由调用方决定是否登出）。
 */
async function refreshAccessToken(): Promise<boolean> {
  if (!_refreshPromise) {
    _refreshPromise = (async () => {
      try {
        await service.post('/auth/refresh', {}, {
          _skipAuthRefresh: true,
        } as RetryableAxiosConfig)
        return true
      } catch {
        return false
      } finally {
        _refreshPromise = null
      }
    })()
  }
  return _refreshPromise
}

service.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const method = config.method?.toLowerCase()
  if (method && ['post', 'put', 'delete', 'patch'].includes(method)) {
    // PC 端登录是 Cookie 认证（无 Bearer），后端不会在响应头设置 X-CSRF-Token，
    // 需从 Cookie 兜底读取，否则首次 POST 请求会 403
    const csrfToken = _csrfCache || getCsrfFromCookie()
    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken
    }
  }
  if (import.meta.env.DEV) {
    devLog(`[API] ${method?.toUpperCase()} ${config.baseURL}${config.url}`)
  }
  return config
})

service.interceptors.response.use(
  (response: AxiosResponse) => {
    const csrfFromHeader = response.headers['x-csrf-token']
    if (csrfFromHeader) {
      _csrfCache = csrfFromHeader as string
    }
    return response.data
  },
  async (error: AxiosError) => {
    if (error.response?.status === 401) {
      const config = error.config as RetryableAxiosConfig | undefined
      const isLoginRequest = config?.url?.includes('/auth/login') ?? false
      // 首次 401：用 refresh_token 刷新 access_token 后重放原请求（登录接口除外）
      if (config && !config._retried && !config._skipAuthRefresh && !isLoginRequest) {
        config._retried = true
        if (await refreshAccessToken()) {
          try {
            // 原 signal 可能已被路由切换 abort；重放不应继承，否则刷新成功也会立刻取消
            config.signal = new AbortController().signal
            return await service(config)
          } catch {
            // 重放仍失败：继续走登出逻辑
          }
        }
      }
      if (!isRedirecting401) {
        isRedirecting401 = true
        window.dispatchEvent(new CustomEvent('auth:expired'))
        setTimeout(() => { isRedirecting401 = false }, 2000)
      }
    }
    if (error.response?.status === 403) {
      const detail = (error.response?.data as { detail?: string })?.detail || '权限不足'
      console.warn('[API 403]', detail)
      if (!isShowing403) {
        isShowing403 = true
        try {
          const { toast } = await import('@/composables/useToast')
          toast.warning(detail, { duration: 3000 })
        } catch { /* composable 不可用时静默降级 */ }
        setTimeout(() => { isShowing403 = false }, 3000)
      }
    }
    return Promise.reject(error)
  },
)

const RETRY_STATUS_CODES = [502, 503, 504]
const MAX_RETRIES = 2
const RETRY_DELAY_MS = 1000

function shouldRetry(error: AxiosError, retryCount: number): boolean {
  if (retryCount >= MAX_RETRIES) return false
  if (error.response && RETRY_STATUS_CODES.includes(error.response.status)) return true
  if (error.code === 'ECONNABORTED' || !error.response) return true
  return false
}

async function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function executeWithRetry<T>(
  fn: () => Promise<T>,
  retryCount = 0,
): Promise<T> {
  try {
    return await fn()
  } catch (error: unknown) {
    if (axios.isAxiosError(error) && shouldRetry(error, retryCount)) {
      const backoff = RETRY_DELAY_MS * Math.pow(2, retryCount)
      await delay(backoff)
      return executeWithRetry(fn, retryCount + 1)
    }
    throw error
  }
}

// GET 请求去重：同一 url+params 的并发 GET 共享同一个 Promise，避免重复网络请求
// 注意：去重的 Promise 包含重试逻辑（executeWithRetry），所有去重调用者会共享重试延迟。
// 如需独立重试或快速失败，请直接使用 service.get()。
const _inflightGet = new Map<string, Promise<unknown>>()

// 路由切换时取消上一路由的未完成 GET，避免旧响应回填新页面
const _pendingControllers = new Set<AbortController>()

export function createTrackedController(): AbortController {
  const controller = new AbortController()
  _pendingControllers.add(controller)
  return controller
}

export function abortPendingRequests(): void {
  for (const controller of _pendingControllers) controller.abort()
  _pendingControllers.clear()
  // 取消的请求不会 settle（见 _silenceCanceled），必须主动清掉去重表，避免永久持有
  _inflightGet.clear()
}

export function isCanceledError(error: unknown): boolean {
  return axios.isCancel(error) || (error as { code?: string } | null)?.code === 'ERR_CANCELED'
}

/**
 * 路由切换取消的请求**不得**触发调用方的 catch/toast：
 * 返回一个永不 settle 的 Promise（调用方的 await 不再继续）。
 * 取消后无外部引用，整条 promise 链可被 GC；去重表由 abortPendingRequests 清空。
 */
export function _silenceCanceled<T>(promise: Promise<T>): Promise<T> {
  return promise.catch((error: unknown) => {
    if (isCanceledError(error)) return new Promise<T>(() => {})
    throw error
  })
}

function _dedupeKey(url: string, params?: Record<string, unknown>): string {
  return `${url}?${params ? JSON.stringify(params) : ''}`
}

export function get<T>(
  url: string,
  params?: Record<string, unknown>,
  options?: { signal?: AbortSignal },
): Promise<T> {
  const key = _dedupeKey(url, params)
  const existing = _inflightGet.get(key)
  if (existing) return existing as Promise<T>
  // 读接口快速失败：单次请求（axios 15s 超时即抛错），不做网络重试。
  // 叠加重试会让 UI 的"加载中"最长挂约 48s；失败后由前端错误态 + 重试按钮兜底。
  const controller = createTrackedController()
  if (options?.signal) {
    if (options.signal.aborted) controller.abort()
    else options.signal.addEventListener('abort', () => controller.abort(), { once: true })
  }
  const raw = service.get(url, { params, signal: controller.signal }) as Promise<T>
  const p = _silenceCanceled(raw)
  _inflightGet.set(key, p)
  // finally 会派生一个与原 Promise 同状态的新 Promise；若原请求失败（403/401/网络错误），
  // 必须 catch 这个派生 Promise，否则每次失败 GET 都会产生一次未处理的 Promise 拒绝（Uncaught (in promise) AxiosError）
  raw.finally(() => {
    _inflightGet.delete(key)
    _pendingControllers.delete(controller)
  }).catch(() => { /* 错误已由调用方处理 */ })
  return p
}

/** 写重试**仅在被调用方显式声明幂等时**生效；命中的网关错误码 */
const WRITE_RETRY_CODES = [502, 503, 504]

/**
 * 写操作重试。
 *
 * ⚠️ 默认**不重试**（`retryable` 必须显式为 true 才重试一次）。
 *
 * 原实现对**所有** POST/PUT/DELETE 在 502/503/504 时无条件重放一次，这是对
 * **非幂等**操作的盲重试：nginx 在「后端已提交、响应途中断连」时正会返回 502，
 * 于是重放 `POST /orders`、`/deduct-stock`、`/approvals/approve` 就是
 * **重复下单 / 重复扣减 / 重复审批**；DELETE 重放还会因二次为 404 而报
 * "删除失败"，但数据其实已删（假失败）。
 *
 * 为什么不能靠"是否收到响应"来判定：浏览器侧**无法区分**「请求根本没送达」与
 * 「已送达并处理、但响应在回程丢失」——任何 HTTP 响应（含 502）或超时都可能属于后者。
 * 因此只有**调用方明确知道该操作幂等**时才允许重试（例如带幂等键、或纯覆盖写）。
 */
async function executeWriteWithRetry<T>(
  fn: () => Promise<T>,
  retryable: boolean,
): Promise<T> {
  try {
    return await fn()
  } catch (error: unknown) {
    if (
      retryable
      && axios.isAxiosError(error) && error.response
      && WRITE_RETRY_CODES.includes(error.response.status)
    ) {
      await delay(RETRY_DELAY_MS)
      return fn() // 仅重试一次
    }
    throw error
  }
}

export function post<T>(url: string, data?: unknown, opts?: { retryable?: boolean }): Promise<T> {
  return executeWriteWithRetry(() => service.post(url, data) as Promise<T>, opts?.retryable === true)
}

export function put<T>(url: string, data?: unknown, opts?: { retryable?: boolean }): Promise<T> {
  return executeWriteWithRetry(() => service.put(url, data) as Promise<T>, opts?.retryable === true)
}

export function del<T>(url: string, opts?: { retryable?: boolean }): Promise<T> {
  return executeWriteWithRetry(() => service.delete(url) as Promise<T>, opts?.retryable === true)
}

/**
 * 文件上传。
 * timeout 可覆盖全局 15s（Excel 解析 + 写暂存通常远超 15s，导入场景需显式放宽）。
 */
export function upload<T>(url: string, formData: FormData, headers?: Record<string, string>, timeout?: number): Promise<T> {
  return service.post(url, formData, { headers, ...(timeout ? { timeout } : {}) }) as Promise<T>
}

/** POST 请求下载文件（用于需要 POST body 的文件下载场景） */
export async function postDownload(url: string, data: unknown, filename: string): Promise<void> {
  // 响应拦截器返回 response.data，因此 res 已是 Blob（responseType: 'blob'）
  const blob = await service.post(url, data, { responseType: 'blob' }) as unknown as Blob
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = filename
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(link.href), 10000)
}

export function download(url: string, filename: string, params?: Record<string, unknown>): Promise<void> {
  return executeWithRetry(() =>
    service.get(url, { responseType: 'blob', params }).then((blob: unknown) => {
      try {
        const link = document.createElement('a')
        link.href = URL.createObjectURL(blob as Blob)
        link.download = filename
        link.click()
        link.remove()
        setTimeout(() => URL.revokeObjectURL(link.href), 10000)
      } catch (e) {
        console.error('Download failed:', e)
        throw e
      }
    }),
  )
}

/**
 * 解析静态资源 URL（相对路径 → 完整 URL）
 *
 * 优先级（自上而下）：
 * 1. 已是 http/https 绝对路径 → 原样返回（直连对象存储等场景）
 * 2. 显式配置 VITE_STATIC_ORIGIN → 使用该域名
 * 3. 浏览器环境 → 同源 /static，由 Vite proxy / nginx 反代转发到后端
 *    - Dev (Vite dev server) → vite.config.ts 的 /static proxy
 *    - Preview (Vite preview) → vite.config.ts 的 preview.proxy
 *    - Production (nginx) → 反代 /static/ → http://127.0.0.1:5002/static/
 *    优点：始终同源，无 CORS / 跨域 cookie 问题
 * 4. SSR → 返回原路径
 */
export function resolveStaticUrl(url: string | null | undefined): string {
  if (!url) return ''
  if (url.startsWith('http') || url.startsWith('//')) return url

  // 1) 显式配置的静态资源专用域名
  const explicit = import.meta.env.VITE_STATIC_ORIGIN
  if (explicit) return explicit + url

  // 2) 浏览器环境：走同源 /static（由反向代理转发到后端）
  if (typeof window !== 'undefined') {
    return `${window.location.origin}${url}`
  }

  // 3) SSR / 测试环境兜底
  return url
}

export default service

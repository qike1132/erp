import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse, AxiosError } from 'axios'
import { getAccessToken } from '@/utils/secureStorage'

// TODO(技术栈优化): 本模块可考虑用原生 fetch 替代 axios 以减小打包体积。
// 当前深度依赖 axios 特性（请求/响应拦截器、isAxiosError 类型守卫、retry 退避逻辑、
// Capacitor 文件下载集成），直接替换风险较高，暂保留。
// 替换时需重写：CSRF token 注入、401 跳转/403 提示、文件上传(multipart)、
// 文件下载(blob/arraybuffer)、502/503/504 重试退避。

const isCap = !!import.meta.env.VITE_CAPACITOR

let isRedirecting401 = false
let isShowing403 = false

// CSRF Token 内存缓存：优先从缓存读取，避免 document.cookie 被 XSS 窃取
// 首次请求时从响应头 x-csrf-token 获取并缓存，后续请求直接使用
let _csrfCache: string | null = null

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
  return match ? decodeURIComponent(match[1]) : ''
}

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
  withCredentials: true,
})

service.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const method = config.method?.toLowerCase()
  if (method && ['post', 'put', 'delete', 'patch'].includes(method)) {
    // CSRF Token 获取优先级：
    //   Capacitor → localStorage('csrf_token') → 响应头缓存
    //   PC 端     → 响应头缓存 → Cookie('fastapi_csrf_token')
    // PC 端登录是 Cookie 认证（无 Bearer），后端不会在响应头设置 X-CSRF-Token，
    // 需从 Cookie 兜底读取，否则首次 POST 请求会 403
    const csrfToken = isCap
      ? (localStorage.getItem('csrf_token') || _csrfCache || getCsrfFromCookie())
      : (_csrfCache || getCsrfFromCookie())
    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken
    }
  }
  if (isCap) {
    const accessToken = getAccessToken()
    if (accessToken && !config.headers['Authorization']) {
      config.headers['Authorization'] = `Bearer ${accessToken}`
    }
    if (import.meta.env.DEV) {
      console.log(`[API] ${method?.toUpperCase()} ${config.baseURL}${config.url}`)
    }
  }
  return config
})

service.interceptors.response.use(
  (response: AxiosResponse) => {
    const csrfFromHeader = response.headers['x-csrf-token']
    if (csrfFromHeader) {
      _csrfCache = csrfFromHeader as string
      if (isCap) {
        localStorage.setItem('csrf_token', csrfFromHeader as string)
      }
    }
    return response.data
  },
  async (error: AxiosError) => {
    if (isCap && import.meta.env.DEV) {
      console.error(`[API Error] ${error.config?.method?.toUpperCase()} ${error.config?.url}`, {
        status: error.response?.status,
        data: error.response?.data,
        message: error.message,
        code: error.code,
      })
    }
    if (error.response?.status === 401) {
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

function _dedupeKey(url: string, params?: Record<string, unknown>): string {
  return `${url}?${params ? JSON.stringify(params) : ''}`
}

export function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const key = _dedupeKey(url, params)
  const existing = _inflightGet.get(key)
  if (existing) return existing as Promise<T>
  const p = executeWithRetry(() => service.get(url, { params }) as Promise<T>)
  _inflightGet.set(key, p)
  p.finally(() => _inflightGet.delete(key))
  return p
}

/** 写操作仅对 502/503/504 网关错误重试一次（不重试 4xx 业务错误） */
const WRITE_RETRY_CODES = [502, 503, 504]

async function executeWriteWithRetry<T>(
  fn: () => Promise<T>,
): Promise<T> {
  try {
    return await fn()
  } catch (error: unknown) {
    if (axios.isAxiosError(error) && error.response && WRITE_RETRY_CODES.includes(error.response.status)) {
      await delay(RETRY_DELAY_MS)
      return fn() // 仅重试一次
    }
    throw error
  }
}

export function post<T>(url: string, data?: unknown): Promise<T> {
  return executeWriteWithRetry(() => service.post(url, data) as Promise<T>)
}

export function put<T>(url: string, data?: unknown): Promise<T> {
  return executeWriteWithRetry(() => service.put(url, data) as Promise<T>)
}

export function del<T>(url: string): Promise<T> {
  return executeWriteWithRetry(() => service.delete(url) as Promise<T>)
}

export function upload<T>(url: string, formData: FormData): Promise<T> {
  return service.post(url, formData) as Promise<T>
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
  if (isCap) {
    return executeWithRetry(() =>
      service.get(url, { responseType: 'arraybuffer', params }).then(async (data: unknown) => {
        const { Filesystem, Directory } = await import('@capacitor/filesystem')
        const { Share } = await import('@capacitor/share')
        const blob = new Blob([data as ArrayBuffer])
        const base64 = await new Promise<string>((resolve) => {
          const reader = new FileReader()
          reader.onload = () => {
            const dataUrl = reader.result as string
            resolve(dataUrl.split(',')[1])
          }
          reader.readAsDataURL(blob)
        })
        const result = await Filesystem.writeFile({
          path: filename,
          data: base64,
          directory: Directory.Cache,
        })
        await Share.share({ url: result.uri, title: filename })
      }),
    )
  }
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
 * 2. Capacitor 模式 → 使用 VITE_STATIC_ORIGIN（移动端独立静态域名）
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

  // 1) Capacitor / 显式配置的静态资源专用域名
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

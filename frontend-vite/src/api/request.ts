import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse, AxiosError } from 'axios'

const service: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  withCredentials: true,
})

service.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const method = config.method?.toLowerCase()
  if (method && ['post', 'put', 'delete', 'patch'].includes(method)) {
    const match = document.cookie.match(/fastapi_csrf_token=([^;]+)/)
    if (match) {
      config.headers['X-CSRF-Token'] = match[1]
    }
  }
  return config
})

service.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      document.cookie = 'auth_status=; path=/; max-age=0'
      const current = window.location.pathname
      if (!current.startsWith('/login')) {
        window.location.href = `/login?redirect=${encodeURIComponent(current)}`
      }
    }
    return Promise.reject(error)
  },
)

const RETRY_STATUS_CODES = [502, 503, 504]
const MAX_RETRIES = 3
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
    const axiosError = error as AxiosError
    if (shouldRetry(axiosError, retryCount)) {
      const backoff = RETRY_DELAY_MS * Math.pow(2, retryCount)
      await delay(backoff)
      return executeWithRetry(fn, retryCount + 1)
    }
    throw error
  }
}

export function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return executeWithRetry(() => service.get(url, { params }) as Promise<T>)
}

export function post<T>(url: string, data?: unknown): Promise<T> {
  return service.post(url, data) as Promise<T>
}

export function put<T>(url: string, data?: unknown): Promise<T> {
  return service.put(url, data) as Promise<T>
}

export function del<T>(url: string): Promise<T> {
  return service.delete(url) as Promise<T>
}

export function upload<T>(url: string, formData: FormData): Promise<T> {
  return service.post(url, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }) as Promise<T>
}

export function download(url: string, filename: string, params?: Record<string, unknown>): Promise<void> {
  return executeWithRetry(() =>
    service.get(url, { responseType: 'blob', params }).then((blob: unknown) => {
      try {
        const link = document.createElement('a')
        link.href = URL.createObjectURL(blob as Blob)
        link.download = filename
        link.click()
        URL.revokeObjectURL(link.href)
      } catch (e) {
        console.error('Download failed:', e)
        throw e
      }
    }),
  )
}

const BACKEND_ORIGIN = import.meta.env.DEV ? 'http://127.0.0.1:5002' : ''

export function resolveStaticUrl(url: string | null | undefined): string {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return BACKEND_ORIGIN + url
}

export default service

import axios from 'axios'
import type { AxiosInstance, InternalAxiosRequestConfig, AxiosResponse } from 'axios'

const service: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  withCredentials: true,
})

// 请求拦截：非读操作自动附加 CSRF Token
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

// 响应拦截：401 重定向 + 统一错误提取
service.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  (error: any) => {
    if (error.response?.status === 401) {
      // 401 时清除本地 auth_status 标记，确保路由守卫不会误判
      document.cookie = 'auth_status=; path=/; max-age=0'
      const current = window.location.pathname
      if (!current.startsWith('/login')) {
        window.location.href = `/login?redirect=${encodeURIComponent(current)}`
      }
    }
    return Promise.reject(error)
  },
)

// 通用请求方法
export function get<T>(url: string, params?: Record<string, any>): Promise<T> {
  return service.get(url, { params }) as Promise<T>
}

export function post<T>(url: string, data?: any): Promise<T> {
  return service.post(url, data) as Promise<T>
}

export function put<T>(url: string, data?: any): Promise<T> {
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

export function download(url: string, filename: string, params?: Record<string, any>): Promise<void> {
  return service.get(url, { responseType: 'blob', params }).then((blob: any) => {
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = filename
    link.click()
    URL.revokeObjectURL(link.href)
  })
}

// 静态资源 URL 解析：开发环境拼接后端地址，生产环境使用相对路径
const BACKEND_ORIGIN = import.meta.env.DEV ? 'http://127.0.0.1:5002' : ''

export function resolveStaticUrl(url: string | null | undefined): string {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return BACKEND_ORIGIN + url
}

export default service

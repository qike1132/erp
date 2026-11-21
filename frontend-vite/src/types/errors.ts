/**
 * 统一错误类型定义与工具函数
 *
 * 用途：替代散落在各组件中的 `catch (err: any)` 模式，
 * 提供类型安全的错误消息提取。
 */

export interface ApiError {
  response?: {
    status?: number
    data?: { detail?: string; message?: string }
  }
  message?: string
}

/** 类型守卫：判断 unknown 值是否为类 Axios 错误 */
export function isApiError(err: unknown): err is ApiError {
  if (typeof err !== 'object' || err === null) return false
  const obj = err as Record<string, unknown>
  return 'response' in obj || 'message' in obj
}

/**
 * L-5 / N-32（2026-11-21 审计）：无 response（网络断开/超时等 axios 原生错误）时，
 * err.message 是英文原文（如 "Network Error" / "timeout of 15000ms exceeded"），
 * 直出对用户不友好——映射为统一中文文案。
 */
const NETWORK_ERROR_MESSAGES: Record<string, string> = {
  'network error': '网络异常，请稍后重试',
  'timeout of': '网络超时，请稍后重试',
}

/** axios 原生英文 message → 统一中文文案；未命中映射表的原样返回 */
function localizeNetworkMessage(message: string): string {
  const lower = message.toLowerCase()
  for (const [prefix, zh] of Object.entries(NETWORK_ERROR_MESSAGES)) {
    if (lower.startsWith(prefix)) return zh
  }
  return message
}

/**
 * 从 API 错误中提取用户可读的错误消息
 *
 * 优先级：detail > message > Error.message（英文网络错误映射中文） > fallback
 */
export function getErrorMessage(err: unknown, fallback = '操作失败，请重试'): string {
  if (!isApiError(err)) {
    return err instanceof Error ? localizeNetworkMessage(err.message) : fallback
  }
  if (!err.response) {
    // 无 response = 请求根本没到服务端（网络断开/超时/CORS），英文原文一律映射
    return err.message ? localizeNetworkMessage(err.message) : fallback
  }
  return err.response?.data?.detail
    || err.response?.data?.message
    || localizeNetworkMessage(err.message || '')
    || fallback
}

/**
 * 从 API 错误中提取 HTTP 状态码
 */
export function getErrorStatus(err: unknown): number | undefined {
  if (!isApiError(err)) return undefined
  return err.response?.status
}

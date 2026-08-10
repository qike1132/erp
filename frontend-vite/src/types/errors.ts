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
 * 从 API 错误中提取用户可读的错误消息
 *
 * 优先级：detail > message > Error.message > fallback
 */
export function getErrorMessage(err: unknown, fallback = '操作失败，请重试'): string {
  if (!isApiError(err)) {
    return err instanceof Error ? err.message : fallback
  }
  return err.response?.data?.detail
    || err.response?.data?.message
    || err.message
    || fallback
}

/**
 * 从 API 错误中提取 HTTP 状态码
 */
export function getErrorStatus(err: unknown): number | undefined {
  if (!isApiError(err)) return undefined
  return err.response?.status
}

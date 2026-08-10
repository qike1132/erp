/**
 * useSamplingHelpers — 打样模块共享工具函数
 *
 * 统一错误处理模式，减少各 Hook 中的重复代码。
 * 纯数据层工具：仅管理 loading/error 状态和 409 自动刷新，
 * 不产生 UI 副作用（toast 由调用方自行决定时机和内容）。
 * 对应 design.md 2.4.6。
 */
import { getErrorMessage, getErrorStatus } from '@/types/errors'

/** 根据 HTTP 状态码解析打样模块操作的错误消息 */
export function resolveSamplingErrorMessage(
  err: unknown,
  fallback: string,
  resourceLabel = '数据',
): string {
  const status = getErrorStatus(err)
  switch (status) {
    case 409:
      return `${resourceLabel}已被他人更新，请刷新后重试`
    case 404:
      return `${resourceLabel}不存在，可能已被删除`
    case 400:
      return getErrorMessage(err, '操作失败，请检查输入')
    default:
      return getErrorMessage(err, fallback)
  }
}

/**
 * 通用 API 调用包装器
 * 自动处理 loading/error 状态、错误弹窗、乐观锁 409 自动刷新。
 *
 * @param fn - 异步 API 调用函数
 * @param options - 配置选项
 * @returns API 调用结果或 null
 */
export async function withErrorHandling<T>(
  fn: () => Promise<T>,
  options: {
    /** 设置 loading 状态 */
    setLoading?: (v: boolean) => void
    /** 设置 error 消息 */
    setError?: (v: string | null) => void
    /** 错误日志前缀 */
    logPrefix?: string
    /** 错误 fallback 消息 */
    fallbackMessage?: string
    /** 资源标签（用于 404/409 消息） */
    resourceLabel?: string
    /** 发生 409 冲突时的自动刷新回调 */
    onConflict?: () => Promise<void>
  } = {},
): Promise<T | null> {
  const {
    setLoading,
    setError,
    logPrefix = '[sampling]',
    fallbackMessage = '操作失败',
    resourceLabel = '数据',
    onConflict,
  } = options

  setLoading?.(true)
  setError?.(null)

  try {
    return await fn()
  } catch (e) {
    console.error(`${logPrefix} 操作失败:`, e)
    const message = resolveSamplingErrorMessage(e, fallbackMessage, resourceLabel)
    setError?.(message)
    // 注意：此处不调用 toast.error()，UI 副作用由调用方自行处理。
    // PatternRoomView 中已有对应 toast 调用（如 toast.error(partHook.error.value || 'xxx')），
    // 此处若再调用会导致双重弹窗。
    if (getErrorStatus(e) === 409 && onConflict) {
      await onConflict()
    }
    return null
  } finally {
    setLoading?.(false)
  }
}

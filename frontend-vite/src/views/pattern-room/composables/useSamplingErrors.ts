/**
 * 打样模块统一的操作错误消息解析（project/part/version/role 各 CRUD hook 共用）
 *
 * - 409 乐观锁冲突：数据已被他人更新，需刷新重试
 * - 404 资源不存在：可能已被删除
 * - 400 业务错误：使用后端返回的 detail
 */
import { getErrorMessage, getErrorStatus } from '@/types/errors'

export function resolveSamplingErrorMessage(
  err: unknown,
  fallback: string,
  opts: { conflict?: string; notFound?: string } = {},
): string {
  const status = getErrorStatus(err)
  if (status === 409) return opts.conflict ?? '数据已被他人更新，请刷新后重试'
  if (status === 404) return opts.notFound ?? '数据不存在，可能已被删除'
  if (status === 400) return getErrorMessage(err, '操作失败，请检查输入')
  return getErrorMessage(err, fallback)
}

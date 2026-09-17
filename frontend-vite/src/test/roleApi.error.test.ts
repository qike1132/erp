import { describe, it, expect } from 'vitest'
import {
  RoleApiError,
  toRoleApiError,
  isRoleReferencedError,
  isRoleNameConflictError,
} from '@/api/role'

/** 构造一个「像 axios 错误」的对象（axios.isAxiosError 只查 isAxiosError === true）。 */
function axiosError(status: number, detail?: string): unknown {
  return {
    isAxiosError: true,
    response: { status, data: detail ? { detail } : {} },
    message: `Request failed with status code ${status}`,
  }
}

describe('role API 错误归类（区分 400 名称冲突 / 409 被引用）', () => {
  it('409 → RoleApiError(409)，detail 含引用数（A-14）', () => {
    const err = toRoleApiError(
      axiosError(409, '角色「爸爸」已被 3 个产品关联，无法删除；请先在相关产品中解绑'),
    )
    expect(err).toBeInstanceOf(RoleApiError)
    expect(err.status).toBe(409)
    expect(isRoleReferencedError(err)).toBe(true)
    expect(isRoleNameConflictError(err)).toBe(false)
    expect(err.detail).toContain('3 个产品')
  })

  it('400 → 名称冲突（与 409 可区分）', () => {
    const err = toRoleApiError(axiosError(400, '角色「爸爸」已存在（名称比较不区分大小写）'))
    expect(err.status).toBe(400)
    expect(isRoleNameConflictError(err)).toBe(true)
    expect(isRoleReferencedError(err)).toBe(false)
  })

  it('404 → 既非冲突也非被引用', () => {
    const err = toRoleApiError(axiosError(404, '角色不存在'))
    expect(err.status).toBe(404)
    expect(isRoleReferencedError(err)).toBe(false)
    expect(isRoleNameConflictError(err)).toBe(false)
  })

  it('网络错误（无 response）→ status 0，透传 message', () => {
    const err = toRoleApiError({ isAxiosError: true, message: 'Network Error' })
    expect(err.status).toBe(0)
    expect(err.detail).toBe('Network Error')
  })

  it('非 axios 异常 → status 0', () => {
    expect(toRoleApiError(new Error('boom')).status).toBe(0)
    expect(toRoleApiError(new Error('boom')).detail).toBe('boom')
    expect(toRoleApiError('oops').detail).toBe('未知错误')
  })

  it('已是 RoleApiError 时原样返回', () => {
    const original = new RoleApiError(409, 'x')
    expect(toRoleApiError(original)).toBe(original)
  })
})

import { describe, it, expect } from 'vitest'
import { resolveCopyTargetRole, type Role } from '../views/product/composables/bomTypes'

describe('resolveCopyTargetRole 复制BOM目标角色解析', () => {
  it('未选中角色（null）→ 默认 BOM 作用域，roleId 为 null', () => {
    expect(resolveCopyTargetRole(null)).toEqual({ ok: true, roleId: null })
  })

  it('选中已保存角色（有 id）→ 透传该 id', () => {
    const role: Role = { id: 42, name: '客户A专属' }
    expect(resolveCopyTargetRole(role)).toEqual({ ok: true, roleId: 42 })
  })

  it('选中未保存的新角色（无 id，有名称）→ 放行并携带 roleName', () => {
    const role: Role = { name: '新建角色' }
    expect(resolveCopyTargetRole(role)).toEqual({ ok: true, roleId: null, roleName: '新建角色' })
  })

  it('仅带 role_key 的新角色（仍无 id）→ 同样放行并携带 roleName', () => {
    const role: Role = { role_key: 'tmp_1', name: '新建角色2' }
    const result = resolveCopyTargetRole(role)
    expect(result.ok).toBe(true)
    expect(result).toEqual({ ok: true, roleId: null, roleName: '新建角色2' })
  })

  it('无 id 且角色名为空 → 防御性中止，提示填写角色名称', () => {
    const role: Role = { name: '   ' }
    expect(resolveCopyTargetRole(role)).toEqual({ ok: false, message: '请填写角色名称' })
  })
})

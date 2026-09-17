import { describe, it, expect } from 'vitest'
import {
  buildRolePayload,
  findRoleByGlobalId,
  type Role,
} from '../views/product/composables/bomTypes'

describe('buildRolePayload BOM 角色负载三路径（A-1 / A-13）', () => {
  it('既有行（有 id）→ 仅传 id + role_name（物料按 id 归属，改名不重建行）', () => {
    expect(buildRolePayload([{ id: 7, global_role_id: 11, name: '客户A' }]))
      .toEqual([{ id: 7, role_name: '客户A' }])
  })

  it('关联已有全局角色（global_role_id）→ 携带 global_role_id（不复制记录）', () => {
    expect(buildRolePayload([{ global_role_id: 11, name: '爸爸' }]))
      .toEqual([{ global_role_id: 11, role_name: '爸爸', name: '爸爸' }])
  })

  it('新建角色（仅 role_key）→ 传 role_key（后端 find-or-create）', () => {
    expect(buildRolePayload([{ role_key: 'rk-1', name: '新建角色' }]))
      .toEqual([{ role_key: 'rk-1', role_name: '新建角色' }])
  })

  it('A-1：两产品引用同一角色 ⇒ 负载携带同一 global_role_id', () => {
    const roleA: Role = { global_role_id: 42, name: '灰姑娘' }
    const roleB: Role = { global_role_id: 42, name: '灰姑娘' }
    const [itemA] = buildRolePayload([roleA])
    const [itemB] = buildRolePayload([roleB])
    expect(itemA?.global_role_id).toBe(42)
    expect(itemB?.global_role_id).toBe(42)
  })

  it('角色名两端空白会被裁剪', () => {
    expect(buildRolePayload([{ role_key: 'rk-2', name: '  白雪公主  ' }]))
      .toEqual([{ role_key: 'rk-2', role_name: '白雪公主' }])
  })
})

describe('findRoleByGlobalId 关联去重（A-1）', () => {
  it('命中已关联的全局角色', () => {
    const roles: Role[] = [
      { id: 1, global_role_id: 5, name: '爸爸' },
      { role_key: 'rk-1', name: '新角色' },
    ]
    expect(findRoleByGlobalId(roles, 5)?.name).toBe('爸爸')
  })

  it('未关联的 global_role_id 返回 undefined', () => {
    expect(findRoleByGlobalId([{ id: 1, global_role_id: 5, name: '爸爸' }], 99)).toBeUndefined()
  })
})

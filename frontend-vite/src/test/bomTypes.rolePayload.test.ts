import { describe, it, expect } from 'vitest'
import { buildRolePayload } from '../views/product/composables/bomTypes'

describe('buildRolePayload BOM 角色负载两条路径（角色为产品私有）', () => {
  it('既有行（有 id）→ 仅传 id + role_name（物料按 id 归属，改名不重建行）', () => {
    expect(buildRolePayload([{ id: 7, name: '客户A' }]))
      .toEqual([{ id: 7, role_name: '客户A' }])
  })

  it('新建角色（仅 role_key）→ 传 role_key，由后端在本产品内复用/新建', () => {
    expect(buildRolePayload([{ role_key: 'rk-1', name: '新建角色' }]))
      .toEqual([{ role_key: 'rk-1', role_name: '新建角色' }])
  })

  it('角色名两端空白会被裁剪', () => {
    expect(buildRolePayload([{ role_key: 'rk-2', name: '  白雪公主  ' }]))
      .toEqual([{ role_key: 'rk-2', role_name: '白雪公主' }])
  })
})

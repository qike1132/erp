import { describe, it, expect } from 'vitest'
import { scopeKeyOf, scopeNameOf, DEFAULT_BOM_LABEL } from '../scope'

/**
 * 作用域助手（原 roleMatrix.spec.ts 中「作用域辅助函数」一节）。
 * 跨角色对比矩阵移除后，只保留这两个仍被结果列 / 移动端复用的纯函数测试。
 */
describe('作用域辅助函数', () => {
  it('scopeKeyOf: null 角色 → default 段', () => {
    expect(scopeKeyOf({ product_id: 7, role_id: null })).toBe('p|7|r|default')
    expect(scopeKeyOf({ product_id: 7, role_id: 9 })).toBe('p|7|r|9')
  })
  it('scopeNameOf: 默认 BOM 无名 → 默认BOM', () => {
    expect(scopeNameOf({ role_id: null, role_name: '  ' })).toBe(DEFAULT_BOM_LABEL)
    expect(scopeNameOf({ role_id: 5, role_name: '  ' })).toBe('角色#5')
    expect(scopeNameOf({ role_id: 5, role_name: ' 爸爸 ' })).toBe('爸爸')
  })
})

/**
 * 分配权限弹窗分组逻辑回归
 *
 * 背景：/user 的「分配权限」弹窗曾与左侧导航栏对不上 —— 弹窗按 permission.section
 * 自行分组，会把导航里没有的顶层权限（is_nav=false 的操作权限、已下线项）也列出来，
 * 并把导航中不存在的 section（如 finance、无 section 项）以原始名追加到末尾
 * （无 section 项甚至显示成 "other"）。
 *
 * 期望：分区顺序 / 命名 / 条目完全以导航栏（navSections）为权威源；匹配不上的
 * 顶层权限收进末尾固定的「其他操作权限」区（key = EXTRAS_SECTION_KEY）。
 */
import { describe, it, expect } from 'vitest'
import {
  buildPermissionSections,
  EXTRAS_SECTION_KEY,
  type NavSectionLike,
} from '@/views/user/composables/useUserManagement'
import type { PermissionItem } from '@/types'

function perm(id: number, code: string, extra: Partial<PermissionItem> = {}): PermissionItem {
  return { id, code, name: code, parent_id: null, ...extra }
}

function nav(title: string, key: string, codes: string[]): NavSectionLike {
  return { title, key, items: codes.map((c) => ({ permission: c })) }
}

/** 取数组元素（越界即失败），规避 noUncheckedIndexedAccess 的 undefined 类型 */
function nth<T>(arr: T[], i: number): T {
  const v = arr[i]
  if (v === undefined) throw new Error(`数组索引 ${i} 越界`)
  return v
}

describe('buildPermissionSections', () => {
  it('分区顺序 / 命名 / 条目照抄导航栏，条目按 code 匹配', () => {
    const tree = [
      perm(1, 'product_manage', { name: '产品管理' }),
      perm(2, 'order_manage', { name: '客户订单' }),
      perm(3, 'user_manage', { name: '用户管理' }),
    ]
    const navs = [
      nav('开发', 'dev', ['product_manage']),
      nav('核心业务', 'core', ['order_manage']),
      nav('系统管理', 'system', ['user_manage']),
    ]
    const sections = buildPermissionSections(tree, navs)
    expect(sections.map((s) => s.key)).toEqual(['dev', 'core', 'system'])
    expect(sections.map((s) => s.name)).toEqual(['开发', '核心业务', '系统管理'])
    expect(nth(sections, 1).items.map((i) => i.name)).toEqual(['客户订单'])
  })

  it('条目顺序跟随导航项顺序，而非权限树顺序', () => {
    const tree = [perm(1, 'a'), perm(2, 'b'), perm(3, 'c')]
    const sections = buildPermissionSections(tree, [nav('核心业务', 'core', ['c', 'a', 'b'])])
    expect(nth(sections, 0).items.map((i) => i.code)).toEqual(['c', 'a', 'b'])
  })

  it('导航项在权限树中缺失时被跳过，不产出空分区', () => {
    const tree = [perm(1, 'product_manage')]
    const navs = [
      nav('开发', 'dev', ['product_manage']),
      nav('湖北订单', 'hubei', ['beile_order_view']),
    ]
    expect(buildPermissionSections(tree, navs).map((s) => s.key)).toEqual(['dev'])
  })

  it('非导航顶层权限收进末尾固定的「其他操作权限」区', () => {
    const tree = [
      perm(1, 'product_manage'),
      perm(2, 'order_batch_manage', { is_nav: false }), // 已从导航下线
      perm(3, 'finance_view', { is_nav: false }),
    ]
    const sections = buildPermissionSections(tree, [nav('开发', 'dev', ['product_manage'])])
    expect(sections).toHaveLength(2)
    expect(nth(sections, 1).key).toBe(EXTRAS_SECTION_KEY)
    expect(nth(sections, 1).name).toBe('其他操作权限')
    expect(nth(sections, 1).items.map((i) => i.code)).toEqual(['order_batch_manage', 'finance_view'])
  })

  it('全部匹配时不产生附加区', () => {
    const sections = buildPermissionSections(
      [perm(1, 'product_manage')],
      [nav('开发', 'dev', ['product_manage'])],
    )
    expect(sections).toHaveLength(1)
    expect(sections.some((s) => s.key === EXTRAS_SECTION_KEY)).toBe(false)
  })

  it('同一权限码被多个导航项引用时只计一次', () => {
    const navs = [
      nav('开发', 'dev', ['product_manage']),
      nav('重复', 'dup', ['product_manage']),
    ]
    const sections = buildPermissionSections([perm(1, 'product_manage')], navs)
    expect(sections).toHaveLength(1)
    expect(nth(sections, 0).items).toHaveLength(1)
  })

  it('权限树为空时返回空数组', () => {
    expect(buildPermissionSections([], [nav('开发', 'dev', ['product_manage'])])).toEqual([])
  })

  it('导航数据为空时全部权限落入附加区', () => {
    const sections = buildPermissionSections([perm(1, 'a'), perm(2, 'b')], [])
    expect(sections).toHaveLength(1)
    expect(nth(sections, 0).key).toBe(EXTRAS_SECTION_KEY)
    expect(nth(sections, 0).items).toHaveLength(2)
  })
})

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
  collectModuleIds,
  collectSectionIds,
  countChecked,
  getPermissionCheckState,
  filterPermissionSections,
  type NavSectionLike,
  type PermissionSection,
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

/**
 * 「分配权限」双栏改版（方案 A）新增的纯函数。
 *
 * 左栏按模块列出勾选进度、右栏只显示当前模块的权限，都需要「把模块/分区展开成
 * id 集合 → 数命中 → 判三态」这套计算；搜索需要按模块名或子权限名过滤。
 * 全部提成纯函数，便于单测（组件只负责渲染与交互）。
 */
describe('权限分配辅助函数（双栏）', () => {
  function sec(key: string, name: string, items: PermissionItem[]): PermissionSection {
    return { key, name, items }
  }

  function parent(id: number, code: string, name: string, children: PermissionItem[]): PermissionItem {
    return { id, code, name, parent_id: null, children }
  }

  describe('collectModuleIds / collectSectionIds', () => {
    it('模块 id 集合含自身与全部子权限', () => {
      const m = parent(1, 'product_manage', '产品清单', [
        perm(2, 'product_create'),
        perm(3, 'product_delete'),
      ])
      expect(collectModuleIds(m)).toEqual([1, 2, 3])
    })

    it('无子权限的模块只含自身', () => {
      expect(collectModuleIds(perm(9, 'backup_manage'))).toEqual([9])
    })

    it('分区 id 集合是各模块 id 集合的并集', () => {
      const s = sec('core', '核心业务', [parent(1, 'a', 'A', [perm(2, 'a2')]), perm(3, 'b')])
      expect(collectSectionIds(s)).toEqual([1, 2, 3])
    })
  })

  describe('countChecked / getPermissionCheckState', () => {
    it('全部命中 → all', () => {
      expect(getPermissionCheckState([1, 2], [1, 2, 3])).toBe('all')
    })

    it('部分命中 → partial', () => {
      expect(getPermissionCheckState([1, 2], [2])).toBe('partial')
    })

    it('全未命中 → none', () => {
      expect(getPermissionCheckState([1, 2], [])).toBe('none')
    })

    it('空 id 集合 → none（不得误判为 all）', () => {
      expect(getPermissionCheckState([], [])).toBe('none')
    })

    it('countChecked 只数命中项', () => {
      expect(countChecked([1, 2, 3], [3, 1, 9])).toBe(2)
    })
  })

  describe('filterPermissionSections', () => {
    const sections: PermissionSection[] = [
      sec('core', '核心业务', [
        parent(1, 'product_manage', '产品清单', [
          perm(2, 'product_import', { name: '导入' }),
        ]),
        perm(3, 'order_manage', { name: '客户订单' }),
      ]),
      sec('system', '系统管理', [perm(4, 'backup_manage', { name: '数据备份' })]),
    ]

    it('空白查询原样返回（分区数不变）', () => {
      expect(filterPermissionSections(sections, '   ').map((s) => s.key)).toEqual(['core', 'system'])
    })

    it('按模块名过滤，命中模块之外的同区模块被剔除', () => {
      const r = filterPermissionSections(sections, '客户')
      expect(r.map((s) => s.key)).toEqual(['core'])
      expect(nth(r, 0).items.map((i) => i.code)).toEqual(['order_manage'])
    })

    it('按子权限名命中时保留其所属模块', () => {
      const r = filterPermissionSections(sections, '导入')
      expect(nth(r, 0).items.map((i) => i.code)).toEqual(['product_manage'])
    })

    it('按分区名命中时保留该分区全部模块', () => {
      const r = filterPermissionSections(sections, '系统')
      expect(r.map((s) => s.key)).toEqual(['system'])
      expect(nth(r, 0).items.map((i) => i.code)).toEqual(['backup_manage'])
    })

    it('无命中返回空数组', () => {
      expect(filterPermissionSections(sections, 'zzz')).toEqual([])
    })

    it('不修改传入的分区数组', () => {
      filterPermissionSections(sections, '客户')
      expect(nth(sections, 0).items).toHaveLength(2)
    })
  })
})

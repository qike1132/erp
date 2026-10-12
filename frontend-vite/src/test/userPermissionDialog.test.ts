/**
 * 「分配权限」弹窗 —— 双栏改版（方案 A）回归
 *
 * 背景：原弹窗是单栏三层嵌套折叠（分区 → 模块 → 权限项），要不停展开折叠、没有搜索、
 * 只有 680px 宽，看不出「到底给了什么」。改版为**双栏主从**：左栏按模块列出勾选进度，
 * 右栏只显示当前模块的权限。
 *
 * 本测试锁住双栏的关键行为：左栏列模块、右栏跟随选中、搜索过滤、三态显示、点击回传。
 * UiDialog 用桩替换（只关心本组件的结构与交互，不测 reka-ui 弹窗机制）。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import UserPermissionDialog from '@/views/user/components/UserPermissionDialog.vue'
import type { PermissionSection } from '@/views/user/composables/useUserManagement'
import type { PermissionItem } from '@/types'

function perm(id: number, code: string, name: string): PermissionItem {
  return { id, code, name, parent_id: null }
}

function parent(id: number, code: string, name: string, children: PermissionItem[]): PermissionItem {
  return { id, code, name, parent_id: null, children }
}

const SECTIONS: PermissionSection[] = [
  {
    key: 'core',
    name: '核心业务',
    items: [
      parent(1, 'product_manage', '产品清单', [
        perm(2, 'product_create', '新增'),
        perm(3, 'product_delete', '删除'),
      ]),
      perm(4, 'order_manage', '客户订单'),
    ],
  },
  { key: 'system', name: '系统管理', items: [perm(5, 'backup_manage', '数据备份')] },
]

/** 已勾选：产品清单 2/3（半选）、客户订单 1/1（全选）、数据备份 0/1（未选） */
const CHECKED = [1, 2, 4]

function mountDialog(overrides: Record<string, unknown> = {}) {
  const checked = (overrides.permCheckedKeys as number[] | undefined) ?? CHECKED
  return mount(UserPermissionDialog, {
    props: {
      open: true,
      permTargetName: '张三',
      permissionSections: SECTIONS,
      permCheckedKeys: checked,
      permIsAllChecked: false,
      permSubmitting: false,
      isPermChecked: (id: number) => checked.includes(id),
      togglePermNode: vi.fn(),
      toggleAllPerms: vi.fn(),
      handleSavePermission: vi.fn(),
      ...overrides,
    },
    global: {
      stubs: {
        UiDialog: { template: '<div><slot /><slot name="footer" /></div>' },
      },
    },
  })
}

describe('UserPermissionDialog 双栏', () => {
  it('左栏列出全部分区与模块', () => {
    const w = mountDialog()
    expect(w.findAll('.pd-sec').map((s) => s.text())).toEqual(['核心业务', '系统管理'])
    expect(w.findAll('.pd-mod-name').map((m) => m.text())).toEqual([
      '产品清单',
      '客户订单',
      '数据备份',
    ])
  })

  it('右栏默认显示第一个模块：模块自身 + 其子权限', () => {
    const w = mountDialog()
    expect(w.find('.pd-right-head h4').text()).toBe('产品清单')
    expect(w.findAll('.pd-row-name').map((r) => r.text())).toEqual([
      '产品清单',
      '新增',
      '删除',
    ])
  })

  it('点击左栏模块切换右栏内容', async () => {
    const w = mountDialog()
    await w.findAll('.pd-mod')[2]!.trigger('click')
    expect(w.find('.pd-right-head h4').text()).toBe('数据备份')
    expect(w.findAll('.pd-row-name').map((r) => r.text())).toEqual(['数据备份'])
  })

  it('搜索按模块名或子权限名过滤左栏，并自动选中首个可见模块', async () => {
    const w = mountDialog()
    await w.find('.pd-search input').setValue('备份')
    expect(w.findAll('.pd-mod-name').map((m) => m.text())).toEqual(['数据备份'])
    expect(w.find('.pd-right-head h4').text()).toBe('数据备份')
  })

  it('搜索无命中时显示空态', async () => {
    const w = mountDialog()
    await w.find('.pd-search input').setValue('zzzz')
    expect(w.findAll('.pd-mod')).toHaveLength(0)
    expect(w.find('.pd-empty').exists()).toBe(true)
  })

  it('左栏模块勾选框呈三态：全选 / 半选 / 未选', () => {
    const w = mountDialog()
    const states = w.findAll('.pd-mod .pd-box').map((b) => b.attributes('aria-checked'))
    expect(states).toEqual(['mixed', 'true', 'false'])
  })

  it('模块行显示已选/总数胶囊', () => {
    const w = mountDialog()
    expect(w.findAll('.pd-pill').map((p) => p.text())).toEqual(['2/3', '1/1', '0/1'])
  })

  it('点击右栏权限行回传 togglePermNode(该权限 id)', async () => {
    const togglePermNode = vi.fn()
    const w = mountDialog({ togglePermNode })
    const rows = w.findAll('.pd-row')
    await rows[2]!.trigger('click') // 「删除」= id 3
    expect(togglePermNode).toHaveBeenCalledWith(3)
  })

  it('点击左栏模块的勾选框只切换权限、不切换选中模块', async () => {
    const togglePermNode = vi.fn()
    const w = mountDialog({ togglePermNode })
    await w.findAll('.pd-mod .pd-box')[2]!.trigger('click') // 数据备份
    expect(togglePermNode).toHaveBeenCalledWith(5)
    expect(w.find('.pd-right-head h4').text()).toBe('产品清单')
  })

  it('底部显示全局已选/总数', () => {
    const w = mountDialog()
    // 全局 5 个权限里勾了 3 个（产品清单 自身+新增、客户订单 自身）
    expect(w.find('.pd-foot-total').text()).toContain('已选 3 / 5 项')
  })
})

/**
 * 行内操作按 /report 的 TAB 归组（变体 B）。
 *
 * 订单流水的子权限是 5 个 tab × 一对「编辑/删除」（迁移 091 起备货也独立），
 * 平铺成 10 行看不出哪个码属于哪个 tab，故按 TAB 归成 5 行、每行两个胶囊。
 */
describe('UserPermissionDialog 行内操作按 TAB 归组', () => {
  const ROW_ACTION_SECTIONS: PermissionSection[] = [
    {
      key: 'data',
      name: '订单查询',
      items: [
        parent(100, 'report_manage', '订单流水', [
          perm(101, 'order_edit', '编辑订单流水'),
          perm(102, 'order_delete', '删除订单流水'),
          perm(103, 'stockin_edit', '编辑备货流水'),
          perm(104, 'stockin_delete', '删除备货流水'),
          perm(105, 'stockout_edit', '编辑出货流水'),
          perm(106, 'stockout_delete', '删除出货流水'),
          perm(107, 'deduction_edit', '编辑备货抵扣流水'),
          perm(108, 'deduction_delete', '删除备货抵扣流水'),
          perm(109, 'return_edit', '编辑退货流水'),
          perm(110, 'return_delete', '删除退货流水'),
        ]),
      ],
    },
  ]

  function mountRowActions(overrides: Record<string, unknown> = {}) {
    return mountDialog({
      permissionSections: ROW_ACTION_SECTIONS,
      permCheckedKeys: [],
      ...overrides,
    })
  }

  it('按 /report 的 5 个 TAB 归成 5 行，顺序与报表页一致', () => {
    const w = mountRowActions()
    expect(w.findAll('.pd-trow')).toHaveLength(5)
    expect(w.findAll('.pd-tnm').map((e) => e.text())).toEqual([
      '订单流水',
      '备货流水',
      '出货流水',
      '备货抵扣流水',
      '退货流水',
    ])
  })

  it('每个 TAB 行有 编辑 / 删除 两个胶囊（共 10 个）', () => {
    expect(mountRowActions().findAll('.pd-trow .pd-op')).toHaveLength(10)
  })

  it('点第 2 个 TAB 的「编辑」胶囊回传该权限 id（备货流水 → stockin_edit）', async () => {
    const togglePermNode = vi.fn()
    const w = mountRowActions({ togglePermNode })
    // 5 行 × (编辑, 删除) 展平后 index 2 = 备货流水的「编辑」
    await w.findAll('.pd-trow .pd-op')[2]!.trigger('click')
    expect(togglePermNode).toHaveBeenCalledWith(103)
  })

  it('子权限不是行内操作码的模块仍走平铺（产品清单）', () => {
    const w = mountDialog()
    expect(w.findAll('.pd-trow')).toHaveLength(0)
    expect(w.findAll('.pd-row').length).toBeGreaterThan(0)
  })
})

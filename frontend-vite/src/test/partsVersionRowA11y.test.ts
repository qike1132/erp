import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import PartsVersionRowV2 from '@/views/pattern-room/components/PartsVersionRowV2.vue'
import {
  createEmptyEditData,
  providePartInlineEdit,
} from '@/views/pattern-room/composables/usePartInlineEdit'
import type { PartDetail } from '@/api/patternRoom'
import type { GroupedRow } from '@/views/pattern-room/composables/usePartsVersionFilter'

/**
 * 行内图标按钮命名回归（/pattern-room 审查 A11Y-21）。
 *
 * 这些按钮只有图标，原来仅靠 `title`。两个后果：
 *   1. 触屏没有 hover，「保存/复制/删除」全靠猜；
 *   2. 历史快照行会被置灰，而多数读屏器**不播报 disabled 元素的 title** ——
 *      用户只听到「按钮，不可用」，既不知道是哪个操作，也不知道为什么。
 * 所以断言的落点是 aria-label 非空且**带行上下文**（部位名 + 版本号），
 * 而不是某个 title 文案。
 */
function makePart(overrides: Partial<PartDetail> = {}): PartDetail {
  return {
    id: 501,
    project_id: 1,
    role_id: 1,
    part_name: '身体',
    sort_order: 1,
    fabric_name: '赛乐绒',
    fabric_spec: '',
    fabric_color_no: '89',
    supplier_id: null,
    supplier_name: '伟昇',
    contact_person: '',
    contact_phone: '',
    unit_price: null,
    delivery_days: null,
    remark: '',
    version: 1,
    version_no: 'v2',
    ...overrides,
  }
}

function makeGroup(part: PartDetail, overrides: Partial<GroupedRow> = {}): GroupedRow {
  return {
    part_name: part.part_name,
    rowSpan: 1,
    items: [part],
    latestVersionNo: 'v2',
    collapsed: false,
    totalVersionCount: 2,
    ...overrides,
  }
}

function mountRow(opts: { canManage?: boolean; part?: PartDetail; group?: Partial<GroupedRow>; editing?: boolean } = {}) {
  const part = opts.part ?? makePart()
  const group = makeGroup(part, opts.group)
  const Row = defineComponent({
    setup() {
      providePartInlineEdit({
        editingPartId: ref<number | undefined>(opts.editing ? (part.id ?? undefined) : undefined),
        editForm: createEmptyEditData(),
        startEdit: () => {},
        saveEdit: () => {},
        cancelEdit: () => {},
        candidatesFor: () => [],
      })
      return () =>
        h('table', [
          h('tbody', [
            h(PartsVersionRowV2, {
              group,
              canManage: opts.canManage ?? true,
              selectedVersion: { [group.part_name]: 'v2' },
            }),
          ]),
        ])
    },
  })
  return mount(Row)
}

describe('行内图标按钮都有可访问名', () => {
  it('每个操作按钮的 aria-label 非空（不依赖 title）', () => {
    const w = mountRow()
    const buttons = w.findAll('.pvt-action-btn')
    expect(buttons.length).toBeGreaterThanOrEqual(3)
    for (const btn of buttons) {
      const label = btn.attributes('aria-label')
      expect(label, `按钮 ${btn.classes().join('.')} 缺 aria-label`).toBeTruthy()
      expect(label!.trim().length).toBeGreaterThan(0)
    }
  })

  it('可操作行的 label 带部位名与版本号（多行时才能区分）', () => {
    const w = mountRow()
    const labels = w.findAll('.pvt-action-btn').map((b) => b.attributes('aria-label'))
    expect(labels.some((l) => l?.includes('复制版本') && l?.includes('身体') && l?.includes('v2'))).toBe(true)
    expect(labels.some((l) => l?.includes('修改版本') && l?.includes('身体'))).toBe(true)
    expect(labels.some((l) => l?.includes('删除版本') && l?.includes('身体'))).toBe(true)
  })

  it('历史快照行：label 说明「不可操作」，且按钮确实置灰', () => {
    const w = mountRow({ part: makePart({ id: null }) })
    const buttons = w.findAll('.pvt-action-btn')
    expect(buttons.length).toBeGreaterThan(0)
    for (const btn of buttons) {
      expect(btn.attributes('aria-label')).toContain('历史快照')
      expect(btn.attributes('disabled')).toBeDefined()
    }
  })

  it('编辑态：保存/取消按钮同样带行上下文', () => {
    const w = mountRow({ editing: true })
    const labels = w.findAll('.pvt-action-btn').map((b) => b.attributes('aria-label') ?? '')
    expect(labels.some((l) => l.startsWith('保存修改') && l.includes('身体') && l.includes('v2'))).toBe(true)
    expect(labels.some((l) => l.startsWith('取消修改') && l.includes('身体'))).toBe(true)
  })

  it('无权限时按钮仍在 DOM（置灰），label 不因 disabled 变空', () => {
    const w = mountRow({ canManage: false })
    for (const btn of w.findAll('.pvt-action-btn')) {
      expect(btn.attributes('disabled')).toBeDefined()
      expect(btn.attributes('aria-label')).toBeTruthy()
    }
  })
})

describe('展开/折叠按钮', () => {
  it('有 aria-label 与 aria-expanded，且随折叠状态翻转', () => {
    const expanded = mountRow({ group: { collapsed: false } })
    const btnExpanded = expanded.get('.pvt-expand-btn')
    expect(btnExpanded.attributes('aria-label')).toBe('折叠其他版本')
    expect(btnExpanded.attributes('aria-expanded')).toBe('true')

    const collapsed = mountRow({ group: { collapsed: true } })
    const btnCollapsed = collapsed.get('.pvt-expand-btn')
    expect(btnCollapsed.attributes('aria-label')).toBe('展开所有版本')
    expect(btnCollapsed.attributes('aria-expanded')).toBe('false')
  })
})

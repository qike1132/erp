import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProjectCardItem from '@/views/pattern-room/components/ProjectCardItem.vue'
import type { ProjectSummary } from '@/api/patternRoom'

/**
 * 卡片交互语义回归（/pattern-room 审查 A11Y-01/02/03）。
 *
 * 这组测试守的是「不退回整体热区」，而不是某个 class 名：
 * 一旦有人把 role="button" 加回卡片根节点，内部的编辑/完成/取消按钮就会被
 * 读屏器压平（ARIA 规定 role="button" 的子代 presentational，axe 报 nested-interactive）。
 * 所以第 1 条与第 4 条是这组测试存在的理由。
 */
function makeProject(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: 101,
    sequence_no: 'SO-001',
    product_name: '米奇公仔',
    product_image_url: '/static/p/101.jpg',
    product_image_thumbnail_url: '/static/p/101-thumb.jpg',
    product_image_blur_url: '/static/p/101-blur.jpg',
    current_version: 'v1',
    status: 'in_progress',
    completed_at: null,
    parts_count: 3,
    updated_at: '2026-10-22T08:00:00',
    ...overrides,
  }
}

function mountCard(props: Record<string, unknown> = {}) {
  return mount(ProjectCardItem, {
    props: {
      proj: makeProject(),
      selected: false,
      makerName: '张三',
      displayNumber: 'SO-001',
      canManage: true,
      ...props,
    },
  })
}

/** 祖先链上是否存在 role="button"（nested-interactive 的判定口径） */
function hasButtonAncestor(el: Element): boolean {
  let cur: Element | null = el.parentElement
  while (cur) {
    if (cur.getAttribute('role') === 'button') return true
    cur = cur.parentElement
  }
  return false
}

describe('ProjectCardItem 不再把整张卡做成 role=button', () => {
  it('根节点没有 role=button / tabindex', () => {
    const w = mountCard()
    const root = w.get('.cgl-project-card')
    expect(root.attributes('role')).toBeUndefined()
    expect(root.attributes('tabindex')).toBeUndefined()
  })

  it('操作按钮与缩略图都没有 role=button 祖先', () => {
    const w = mountCard()
    const actions = w.findAll('.cgl-card-action')
    expect(actions.length).toBe(3)
    for (const btn of actions) {
      expect(hasButtonAncestor(btn.element)).toBe(false)
    }
    expect(hasButtonAncestor(w.get('.cgl-card-thumb').element)).toBe(false)
  })
})

describe('ProjectCardItem 三个平级可聚焦元素', () => {
  it('缩略图是原生 button，可访问名带产品名', () => {
    const w = mountCard()
    const thumb = w.get('.cgl-card-thumb')
    expect(thumb.element.tagName).toBe('BUTTON')
    expect(thumb.attributes('type')).toBe('button')
    expect(thumb.attributes('aria-label')).toContain('米奇公仔')
    expect(thumb.attributes('aria-label')).toContain('大图')
  })

  it('名称是原生 button（键盘可达，Enter/Space 均由浏览器激活）', () => {
    const w = mountCard()
    const select = w.get('.cgl-card-select')
    expect(select.element.tagName).toBe('BUTTON')
    expect(select.text()).toContain('米奇公仔')
  })

  it('选中态用 aria-current 表达，未选中时不出现该属性', async () => {
    const w = mountCard({ selected: true })
    expect(w.get('.cgl-card-select').attributes('aria-current')).toBe('true')

    // 非选中：属性应缺省，而不是 "false"（aria-current 的 false 与缺省等价，
    // 但缺省更干净，也避免读屏器逐项念「当前：否」）
    await w.setProps({ selected: false })
    expect(w.get('.cgl-card-select').attributes('aria-current')).toBeUndefined()
  })

  it('无图片时占位分支不产生交互元素', () => {
    const w = mountCard({
      proj: makeProject({ product_image_url: null, product_image_thumbnail_url: null, product_image_blur_url: null }),
    })
    expect(w.find('.cgl-card-thumb').element.tagName).toBe('DIV')
    expect(w.find('.cgl-card-thumb').attributes('aria-label')).toBeUndefined()
  })

  it('canManage=false 时不渲染操作按钮', () => {
    const w = mountCard({ canManage: false })
    expect(w.findAll('.cgl-card-action')).toHaveLength(0)
  })
})

describe('ProjectCardItem 事件互不串扰', () => {
  it('点名称按钮 emit select(项目 id)', async () => {
    const w = mountCard()
    await w.get('.cgl-card-select').trigger('click')
    expect(w.emitted('select')).toEqual([[101]])
    expect(w.emitted('preview')).toBeUndefined()
  })

  it('点缩略图只 emit preview，不触发 select', async () => {
    const w = mountCard()
    await w.get('.cgl-card-thumb').trigger('click')
    expect(w.emitted('preview')).toEqual([['/static/p/101.jpg']])
    expect(w.emitted('select')).toBeUndefined()
  })

  it('点编辑/完成/取消各自 emit，不触发 select', async () => {
    const w = mountCard()
    const [edit, complete, cancel] = w.findAll('.cgl-card-action')
    await edit!.trigger('click')
    await complete!.trigger('click')
    await cancel!.trigger('click')

    expect(w.emitted('edit')).toEqual([[101]])
    expect(w.emitted('complete')).toEqual([[101]])
    expect(w.emitted('cancel')).toEqual([[101]])
    expect(w.emitted('select')).toBeUndefined()
  })
})

import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
// 样式断言需要源码文本：jsdom 不实现 object-fit 的计算样式
// 2026-10-22：样式块外置到同名 .css（SFC 行数超阈值），两处都要读
import cardSource from '@/views/pattern-room/components/ProjectCardItem.vue?raw'
import cardStyles from '@/views/pattern-room/components/ProjectCardItem.css?raw'
import ProjectCardItem from '@/views/pattern-room/components/ProjectCardItem.vue'
import type { ProjectSummary } from '@/api/patternRoom'

/**
 * 打样项目卡片缩略图回归测试
 *
 * 背景：91d602a7 把 .cgl-thumb-img 从 contain 改成 cover 铺满左栏，非正方形
 * 产品图的边缘被裁掉、主体常被切。这里钉住 contain：整张产品图完整可见。
 */
describe('ProjectCardItem 缩略图完整性', () => {
  it('卡片缩略图使用 contain，保证整张产品图可见（cover 会裁切非正方形图片）', () => {
    const imageRule = `${cardSource}\n${cardStyles}`.match(/\.cgl-thumb-img \{[\s\S]*?\}/)?.[0] ?? ''

    expect(imageRule).toContain('object-fit: contain')
    expect(imageRule).not.toContain('object-fit: cover')
  })
})

/**
 * 卡片「完成」后图片变模糊的回归（2026-11-05）
 *
 * 背景：点击「完成」→ 状态写库 → loadGrouped(..., 'silent') 静默刷新，列表里的
 * proj 对象被整体替换。签名 URL 的 st 按小时对齐（signed_urls.py），同一小时内
 * 重新签发的 URL 逐字节相同，因此 <img> 的 src 不变、浏览器不会再派发 load 事件。
 * 旧实现的 watch 源是 `[url, thumbUrl]` 数组字面量——每次求值都是新引用，
 * hasChanged 恒为 true，于是「对象被替换」被误判成「URL 变了」：thumbLoaded 复位为
 * false，.is-loaded 摘掉，模糊占位图重新显形且永远不会淡出（图片卡在模糊态）。
 *
 * 判据不看内部 ref，只看用户能看到的类名：.is-loaded 在，清晰图才不透明。
 */
function makeProject(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: 101,
    sequence_no: 'SO-001',
    product_name: '西瓜墩墩鸡',
    product_image_url: '/static/uploads/p101.webp?st=1&s=sig',
    product_image_thumbnail_url: '/static/uploads/p101-thumb.webp?st=1&s=sig',
    product_image_blur_url: '/static/uploads/p101-blur.webp?st=1&s=sig',
    current_version: 'v1',
    status: 'in_progress',
    completed_at: null,
    parts_count: 0,
    updated_at: '2026-10-19T09:20:00',
    ...overrides,
  }
}

function mountCard(proj: ProjectSummary = makeProject()) {
  return mount(ProjectCardItem, {
    props: {
      proj,
      selected: false,
      makerName: '陈燕凤',
      displayNumber: '2026101901',
      canManage: true,
    },
  })
}

describe('ProjectCardItem 缩略图状态机', () => {
  it('标记完成触发的静默刷新（proj 对象被替换、URL 不变）不得让清晰图退回模糊态', async () => {
    const w = mountCard()
    await w.get('.cgl-thumb-img').trigger('load')
    expect(w.get('.cgl-card-thumb').classes()).toContain('is-loaded')

    // 静默刷新：整条数据是新对象，图片三字段与一小时内的签名 URL 完全一致
    await w.setProps({
      proj: makeProject({ status: 'completed', completed_at: '2026-11-05T08:00:00', updated_at: '2026-11-05T08:00:00' }),
    })

    expect(w.get('.cgl-thumb-img').attributes('src')).toBe('/static/uploads/p101-thumb.webp?st=1&s=sig')
    expect(w.get('.cgl-card-thumb').classes()).toContain('is-loaded')
  })

  it('缩略图 URL 真正变化时才复位为模糊占位，等待新图加载', async () => {
    const w = mountCard()
    await w.get('.cgl-thumb-img').trigger('load')
    expect(w.get('.cgl-card-thumb').classes()).toContain('is-loaded')

    await w.setProps({
      proj: makeProject({ product_image_thumbnail_url: '/static/uploads/p101-thumb-v2.webp?st=2&s=sig2' }),
    })

    expect(w.get('.cgl-thumb-img').attributes('src')).toBe('/static/uploads/p101-thumb-v2.webp?st=2&s=sig2')
    expect(w.get('.cgl-card-thumb').classes()).not.toContain('is-loaded')

    // 新图加载完成后重新淡入
    await w.get('.cgl-thumb-img').trigger('load')
    expect(w.get('.cgl-card-thumb').classes()).toContain('is-loaded')
  })
})

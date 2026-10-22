import { describe, it, expect } from 'vitest'
// 样式断言需要源码文本：jsdom 不实现 object-fit 的计算样式
import cardSource from '@/views/pattern-room/components/ProjectCardItem.vue?raw'

/**
 * 打样项目卡片缩略图回归测试
 *
 * 背景：91d602a7 把 .cgl-thumb-img 从 contain 改成 cover 铺满左栏，非正方形
 * 产品图的边缘被裁掉、主体常被切。这里钉住 contain：整张产品图完整可见。
 */
describe('ProjectCardItem 缩略图完整性', () => {
  it('卡片缩略图使用 contain，保证整张产品图可见（cover 会裁切非正方形图片）', () => {
    const imageRule = cardSource.match(/\.cgl-thumb-img \{[\s\S]*?\}/)?.[0] ?? ''

    expect(imageRule).toContain('object-fit: contain')
    expect(imageRule).not.toContain('object-fit: cover')
  })
})

/**
 * P-0 回归：VirtualList 变高测量的「自相矛盾」修复（RC-4）。
 *
 * 修复前：`getItemStyle` 给每项写死 inline `height`（初值 estimatedHeight），
 *   `measureItems` 量的正是这个被约束后的盒子 → 永远学不到内容真实高度。
 * 修复后：改用品 inline `min-height` 占位 + 量「首个元素子节点（插槽内容根）」
 *   的自然高度 → 展开/收起都能学到真实高度。
 *
 * jsdom 不做布局，这里用元素的 inline `height` 作为 `getBoundingClientRect().height`
 * 的替身，使「插槽内容根节点的自然高」可被确定性地观测。
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import VirtualList from '@/components/ui/VirtualList.vue'

interface Cell {
  id: number
  h: number
}

const SLOT = '<div class="cell" :style="{ height: item.h + \'px\' }" />'

function mountList(items: Cell[]) {
  return mount(VirtualList, {
    props: {
      items,
      itemHeight: 54,
      estimatedHeight: 54,
      containerHeight: 600,
      dynamicHeight: true,
      itemKey: (i: unknown) => (i as Cell).id,
    },
    slots: { default: SLOT },
  })
}

describe('VirtualList 变高测量（P-0 / RC-4）', () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
      configurable: true,
      value(this: HTMLElement) {
        const h = parseFloat(this.style.height || '0') || 0
        return {
          height: h, width: 0, top: 0, left: 0, right: 0, bottom: h, x: 0, y: 0,
          toJSON() { return {} },
        }
      },
    })
  })

  it('变高模式用 min-height 占位（不再写死 height）', async () => {
    const wrapper = mountList([{ id: 0, h: 120 }, { id: 1, h: 60 }])
    await nextTick()
    const style = wrapper.findAll('.virtual-list-item')[0]!.attributes('style') || ''
    expect(style).toContain('min-height')
  })

  it('measureItems 学到的内容自然高驱动总高（120+60=180，而非 54+54=108）', async () => {
    const wrapper = mountList([{ id: 0, h: 120 }, { id: 1, h: 60 }])
    await nextTick()

    // 未测量前：按 estimatedHeight 估算
    expect(wrapper.find('.virtual-list-phantom').attributes('style')).toContain('height: 108px')

    ;(wrapper.vm as unknown as { measureItems: () => void }).measureItems()
    await nextTick()

    // 测量后：学到真实内容高
    expect(wrapper.find('.virtual-list-phantom').attributes('style')).toContain('height: 180px')
    const items = wrapper.findAll('.virtual-list-item')
    expect(items[0]!.attributes('style')).toContain('min-height: 120px')
    expect(items[1]!.attributes('style')).toContain('min-height: 60px')
  })

  it('内容变矮后 remeasureItem + measureItems 能重新学到更小的高（收起不再被 min-height 顶住）', async () => {
    const heights = ref<Cell[]>([{ id: 0, h: 120 }, { id: 1, h: 60 }])
    const wrapper = mount(VirtualList, {
      props: {
        items: heights.value,
        itemHeight: 54,
        estimatedHeight: 54,
        containerHeight: 600,
        dynamicHeight: true,
        itemKey: (i: unknown) => (i as Cell).id,
      },
      slots: { default: SLOT },
    })
    await nextTick()
    const vm = wrapper.vm as unknown as {
      measureItems: () => void
      remeasureItem: (i: number) => void
    }
    vm.measureItems()
    await nextTick()
    expect(wrapper.find('.virtual-list-phantom').attributes('style')).toContain('height: 180px')

    // 内容变矮（模拟 SKU 明细收起）
    await wrapper.setProps({ items: [{ id: 0, h: 40 }, { id: 1, h: 30 }] })
    await nextTick()
    vm.remeasureItem(0)
    vm.remeasureItem(1)
    vm.measureItems()
    await nextTick()

    expect(wrapper.find('.virtual-list-phantom').attributes('style')).toContain('height: 70px')
  })
})

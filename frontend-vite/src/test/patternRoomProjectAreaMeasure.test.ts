import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { useVirtualAreaMeasure } from '@/views/pattern-room/composables/useVirtualAreaMeasure'
import CustomerProjectArea from '@/views/pattern-room/components/CustomerProjectArea.vue'
import type { PatternMakerGroup, ProjectSummary } from '@/api/patternRoom'

/**
 * 线上 BUG（2026-10-23）：/pattern-room 切到「已取消」后点版师，右侧一直「加载中…」，不显示项目。
 *
 * 根因：useVirtualAreaMeasure 只在组件 onMounted 那一刻给容器挂 ResizeObserver 并测高，
 * 而容器元素只有在「选中了版师且该版师有项目」时才渲染（CustomerProjectArea 的 v-else 分支）。
 * 切状态筛选后原选中版师不在新分组里 → selectedGroup 为 null → 容器不存在；
 * 用户再点版师时容器才出现，此后再没有任何测高触发（groups 没变、ResizeObserver 没挂上），
 * height 永远停在 0，模板 `projectAreaHeight <= 0` 恒真 → 永久「加载中…」。
 *
 * 不变量：容器元素「后出现」时，也必须完成测高并挂上尺寸监听。
 */

const STUB_HEIGHT = 480
let stubbedHeight = STUB_HEIGHT
const originalOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')

beforeEach(() => {
  stubbedHeight = STUB_HEIGHT
  // jsdom 不做布局，offsetHeight 恒为 0；这里伪造「容器有真实高度」的浏览器行为
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get: () => stubbedHeight,
  })
})

afterEach(() => {
  if (originalOffsetHeight) {
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', originalOffsetHeight)
  }
})

async function settle(): Promise<void> {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 20))
  await nextTick()
}

describe('useVirtualAreaMeasure：测量容器后出现', () => {
  it('容器在挂载后才出现时仍会被测高（否则高度恒 0）', async () => {
    const show = ref(false)
    let measured: ReturnType<typeof useVirtualAreaMeasure> | null = null

    const Probe = defineComponent({
      setup() {
        measured = useVirtualAreaMeasure()
        return () => h('div', [
          show.value ? h('div', { ref: measured!.areaRef, style: 'height:100%' }) : null,
        ])
      },
    })

    const wrapper = mount(Probe)
    // 挂载时容器不存在：沿用旧实现就再也测不到
    expect(measured!.height.value).toBe(0)
    // 先让挂载期的同步/nextTick/rAF 三轮补测全部耗尽 —— 线上是用户几秒后才点版师
    await settle()
    expect(measured!.height.value).toBe(0)

    show.value = true
    await settle()

    expect(measured!.height.value).toBe(STUB_HEIGHT)
    wrapper.unmount()
  })

  it('元素挂载时已存在也会被测高（不依赖 onMounted 兜底）', async () => {
    let measured: ReturnType<typeof useVirtualAreaMeasure> | null = null

    const Probe = defineComponent({
      setup() {
        measured = useVirtualAreaMeasure()
        return () => h('div', [h('div', { ref: measured!.areaRef, style: 'height:100%' })])
      },
    })

    const wrapper = mount(Probe)
    await settle()

    expect(measured!.height.value).toBe(STUB_HEIGHT)
    wrapper.unmount()
  })

  it('元素摘除时高度归零，再次出现按新容器高度重新测量', async () => {
    const show = ref(true)
    let measured: ReturnType<typeof useVirtualAreaMeasure> | null = null

    const Probe = defineComponent({
      setup() {
        measured = useVirtualAreaMeasure()
        return () => h('div', [
          show.value ? h('div', { ref: measured!.areaRef, style: 'height:100%' }) : null,
        ])
      },
    })

    const wrapper = mount(Probe)
    await settle()
    expect(measured!.height.value).toBe(STUB_HEIGHT)

    // 摘除：必须归零，否则消费方会先拿旧高度渲染，且补测会被 height > 0 早退跳过
    show.value = false
    await settle()
    expect(measured!.height.value).toBe(0)

    // 再次出现且尺寸已变：必须按新高度重新测量
    stubbedHeight = 320
    show.value = true
    await settle()
    expect(measured!.height.value).toBe(320)

    wrapper.unmount()
  })
})

function makeProject(id: number): ProjectSummary {
  return {
    id,
    sequence_no: `SO-${id}`,
    product_name: `项目${id}`,
    product_image_url: null,
    product_image_thumbnail_url: null,
    product_image_blur_url: null,
    current_version: '1',
    status: 'cancelled',
    completed_at: null,
    parts_count: 0,
    updated_at: '2026-10-20 10:00:00',
  }
}

const GROUP_WITH_PROJECT: PatternMakerGroup = {
  pattern_maker_id: 1,
  pattern_maker_name: '红霞',
  project_count: 1,
  latest_update_time: '2026-10-20 10:00:00',
  projects: [makeProject(101)],
}

describe('CustomerProjectArea：选中版师后不得停在「加载中…」', () => {
  it('先渲染空态、再选中版师时，项目卡片正常渲染而不是永久加载中', async () => {
    const wrapper = mount(CustomerProjectArea, {
      props: {
        selectedGroup: null,
        selectedProjectId: null,
        canManage: true,
        groups: [GROUP_WITH_PROJECT],
        selectedMakerKey: null,
        projectDisplayNumbers: new Map<number, string>(),
      },
    })

    // 切换筛选后原选中版师不在新分组里：先看到空态
    expect(wrapper.find('.cgl-list-scroll').exists()).toBe(false)
    // 挂载期补测耗尽后再选中版师（线上是用户随后点击，groups 本身不变）
    await settle()

    await wrapper.setProps({ selectedGroup: GROUP_WITH_PROJECT })
    await settle()

    const loading = wrapper.find('.cgl-list-scroll .ui-loading-status')
    expect(loading.exists()).toBe(true)
    // 关键断言：高度已测出 → loading 必须收起、虚拟列表必须渲染
    expect(loading.classes()).toContain('is-idle')
    expect(wrapper.find('.virtual-list-container').exists()).toBe(true)
    expect(wrapper.text()).toContain('项目101')

    wrapper.unmount()
  })
})

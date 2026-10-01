/**
 * HubeiRouteTabs 外发 TAB 导航回归
 *
 * 业务规则（方案B，docs/outsource/外发模块TAB重构方案.md）：
 * - 三个 TAB 从左到右：外发进度、发货单、工序预设；裸路径 /outsource 落地「外发进度」
 * - 「发货单」对全部角色同名（贝乐在该页确认收货，页面主体即发货单台账）
 * - 「工序预设」对贝乐账号隐藏（贝乐只收货，不维护工序预设）
 * - TAB → 路由映射契约：orders→/outsource、shipments→/outsource/shipments、presets→/outsource/presets
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'

/** 当前测试用户名与路由路径（useRoute 的 mock 按引用返回，可逐用例改写） */
let currentUsername = 'admin'
let currentPath = '/outsource'
const pushMock = vi.fn()

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    hasAnyPermission: () => true,
    user: { get username() { return currentUsername } },
  }),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ path: currentPath }),
  useRouter: () => ({ push: pushMock }),
}))

// stub 需透传 value/active 才能断言激活态推导；命名 stub 便于 findComponent 触发 update:modelValue
const UiTabsStub = { name: 'UiTabsStub', template: '<div class="ui-tabs"><slot /></div>' }
const UiTabTriggerStub = {
  name: 'UiTabTriggerStub',
  props: {
    value: { type: String, default: '' },
    active: { type: Boolean, default: false },
  },
  template: '<button class="ui-tab-btn" :data-active="active ? \'1\' : \'0\'" :data-value="value"><slot /></button>',
}

function mountTabs() {
  return mount(HubeiRouteTabs, {
    global: {
      stubs: {
        FontAwesomeIcon: { template: '<i />' },
        // reka-ui 的 Tabs 依赖注入较复杂，stub 成透传容器即可验证标签与顺序
        UiTabs: UiTabsStub,
        UiTabTrigger: UiTabTriggerStub,
      },
    },
  })
}

/** 全部 TAB 的文本 */
function tabTexts(wrapper: ReturnType<typeof mountTabs>): string[] {
  return wrapper.findAll('.ui-tab-btn').map((b) => b.text())
}

/** 按渲染顺序取各 TAB 的激活标记 */
function activeFlags(wrapper: ReturnType<typeof mountTabs>): string[] {
  return wrapper.findAll('.ui-tab-btn').map((b) => b.attributes('data-active') || '0')
}

beforeEach(() => {
  vi.clearAllMocks()
  currentUsername = 'admin'
  currentPath = '/outsource'
})

describe('HubeiRouteTabs 外发 TAB 导航（方案B）', () => {
  it('非贝乐：三个 TAB 顺序为 外发进度 → 发货单 → 工序预设', () => {
    currentUsername = 'admin'
    expect(tabTexts(mountTabs())).toEqual(['外发进度', '发货单', '工序预设'])
  })

  it('贝乐：隐藏「工序预设」，只剩 外发进度 → 发货单', () => {
    currentUsername = '贝乐'
    const texts = tabTexts(mountTabs())
    expect(texts).toEqual(['外发进度', '发货单'])
    expect(texts.join('|')).not.toContain('工序预设')
  })

  it('「发货单」对贝乐同名（不再使用旧双名「收货」）', () => {
    currentUsername = '贝乐'
    expect(tabTexts(mountTabs())).toContain('发货单')
    expect(tabTexts(mountTabs()).join('|')).not.toContain('收货')
  })

  it('不再出现旧文案「外发工序」与单独的「发货」', () => {
    currentUsername = 'admin'
    expect(tabTexts(mountTabs()).join('|')).not.toContain('外发工序')
    expect(tabTexts(mountTabs())).not.toContain('发货')
    currentUsername = '贝乐'
    expect(tabTexts(mountTabs()).join('|')).not.toContain('外发工序')
  })

  it('activeTab 推导：三个路由各自高亮对应 TAB', () => {
    currentPath = '/outsource'
    expect(activeFlags(mountTabs())).toEqual(['1', '0', '0'])
    currentPath = '/outsource/shipments'
    expect(activeFlags(mountTabs())).toEqual(['0', '1', '0'])
    currentPath = '/outsource/presets'
    expect(activeFlags(mountTabs())).toEqual(['0', '0', '1'])
  })

  it('TAB→路由映射：切换 TAB push 到 TAB_PATHS 约定路径', async () => {
    const wrapper = mountTabs()
    const tabs = wrapper.findComponent({ name: 'UiTabsStub' })
    expect(tabs.exists()).toBe(true)

    tabs.vm.$emit('update:modelValue', 'shipments')
    await wrapper.vm.$nextTick()
    expect(pushMock).toHaveBeenCalledWith('/outsource/shipments')

    tabs.vm.$emit('update:modelValue', 'presets')
    await wrapper.vm.$nextTick()
    expect(pushMock).toHaveBeenCalledWith('/outsource/presets')

    // 同路径不重复 push + orders 分支：重挂到 /outsource/presets 再切「外发进度」
    //（route.path 在 setup 时快照，改路径须重新挂载）
    currentPath = '/outsource/presets'
    const wrapper2 = mountTabs()
    wrapper2.findComponent({ name: 'UiTabsStub' }).vm.$emit('update:modelValue', 'orders')
    await wrapper2.vm.$nextTick()
    expect(pushMock).toHaveBeenCalledWith('/outsource')
  })
})

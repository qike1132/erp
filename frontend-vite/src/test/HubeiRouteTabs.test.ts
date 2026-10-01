/**
 * HubeiRouteTabs 外发 TAB 导航回归
 *
 * 业务规则（方案B，docs/outsource/外发模块TAB重构方案.md）：
 * - 三个 TAB 从左到右：外发进度、发货单、工序预设；裸路径 /outsource 落地「外发进度」
 * - 「发货单」对全部角色同名（贝乐在该页确认收货，页面主体即发货单台账）
 * - 「工序预设」对贝乐账号隐藏（贝乐只收货，不维护工序预设）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'

/** 当前测试用户名 */
let currentUsername = 'admin'
const pushMock = vi.fn()

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    hasAnyPermission: () => true,
    user: { get username() { return currentUsername } },
  }),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/outsource' }),
  useRouter: () => ({ push: pushMock }),
}))

function mountTabs() {
  return mount(HubeiRouteTabs, {
    global: {
      stubs: {
        FontAwesomeIcon: { template: '<i />' },
        // reka-ui 的 Tabs 依赖注入较复杂，stub 成透传容器即可验证标签与顺序
        UiTabs: { template: '<div class="ui-tabs"><slot /></div>' },
        UiTabTrigger: { template: '<button class="ui-tab-btn"><slot /></button>' },
      },
    },
  })
}

/** 全部 TAB 的文本 */
function tabTexts(wrapper: ReturnType<typeof mountTabs>): string[] {
  return wrapper.findAll('.ui-tab-btn').map((b) => b.text())
}

beforeEach(() => {
  vi.clearAllMocks()
  currentUsername = 'admin'
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
})

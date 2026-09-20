/**
 * HubeiRouteTabs 外发 TAB 导航回归
 *
 * 业务规则：
 * - 三个 TAB 从左到右：收货/发货、外发工序、工序预设
 * - 首个 TAB 双名：贝乐账号只收货不发货，显示「收货」；其余账号显示「发货」
 *   （与 OutsourceShipmentView 的 isBeile、后端脚本 BEILE_USERNAME='贝乐' 判定一致）
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

describe('HubeiRouteTabs 外发 TAB 导航', () => {
  it('非贝乐用户：首个 TAB 显示「发货」', () => {
    currentUsername = 'admin'
    const wrapper = mountTabs()
    const texts = tabTexts(wrapper)
    expect(texts[0]).toBe('发货')
    expect(texts.join('|')).not.toContain('收货')
  })

  it('贝乐用户：首个 TAB 显示「收货」', () => {
    currentUsername = '贝乐'
    const wrapper = mountTabs()
    const texts = tabTexts(wrapper)
    expect(texts[0]).toBe('收货')
  })

  it('非贝乐：三个 TAB 顺序为 发货 → 外发工序 → 工序预设', () => {
    currentUsername = 'admin'
    expect(tabTexts(mountTabs())).toEqual(['发货', '外发工序', '工序预设'])
  })

  it('贝乐：隐藏「工序预设」，只剩 收货 → 外发工序', () => {
    currentUsername = '贝乐'
    const texts = tabTexts(mountTabs())
    expect(texts).toEqual(['收货', '外发工序'])
    expect(texts.join('|')).not.toContain('工序预设')
  })

  it('不再出现旧文案「发货单」', () => {
    currentUsername = 'admin'
    expect(tabTexts(mountTabs()).join('|')).not.toContain('发货单')
    currentUsername = '贝乐'
    expect(tabTexts(mountTabs()).join('|')).not.toContain('发货单')
  })
})

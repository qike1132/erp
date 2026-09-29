/**
 * 侧边栏分组多开回归
 *
 * 背景：历史实现用单个 `openSection: string | null` 记录当前分组，属互斥手风琴——
 * 点开「湖北订单」会强制收起「采购中心」「核心业务」等其它分组。
 *
 * 期望：各分组相互独立，可同时展开；路由切换只补开当前分组，
 * 不关闭用户已手动展开的其它分组。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const mocks = vi.hoisted(() => ({
  sections: [
    { title: '湖北订单', items: [{ path: '/hubei-orders', title: '订单录入', icon: 'fa-file' }] },
    { title: '采购中心', items: [{ path: '/purchase', title: '采购管理', icon: 'fa-cart' }] },
    { title: '核心业务', items: [{ path: '/core', title: '核心流程', icon: 'fa-star' }] },
    { title: '订单查询', items: [{ path: '/orders', title: '订单列表', icon: 'fa-list' }] },
    { title: '系统管理', items: [{ path: '/system', title: '系统设置', icon: 'fa-cog' }] },
  ],
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ filteredNavSections: mocks.sections }),
}))

import { useSidebarNav } from '@/layouts/composables/useSidebarNav'

const ALL_TITLES = mocks.sections.map((s) => s.title)

/** 承载 composable 的最小宿主组件，避免同时拉起整个侧边栏 DOM */
const Host = defineComponent({
  setup() {
    const nav = useSidebarNav()
    return {
      toggleSection: nav.toggleSection,
      openTitles: () => ALL_TITLES.filter((t) => nav.sectionIsOpen(t)),
    }
  },
  render: () => h('div'),
})

const ROUTES = mocks.sections.map((s) => ({
  path: s.items[0]!.path,
  component: { template: '<div />' },
}))

async function setup(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: ROUTES })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(Host, { global: { plugins: [router] } })
  return { wrapper, router }
}

/** 当前展开的分组标题 */
function openTitles(wrapper: ReturnType<typeof mount>): string[] {
  return (wrapper.vm as unknown as { openTitles: () => string[] }).openTitles()
}

describe('侧边栏分组多开', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('初始只展开当前路由所在分组', async () => {
    const { wrapper } = await setup('/purchase')
    expect(openTitles(wrapper)).toEqual(['采购中心'])
  })

  it('点击第二个分组后两个分组同时展开（不再互斥）', async () => {
    const { wrapper } = await setup('/purchase')
    const vm = wrapper.vm as unknown as { toggleSection: (t: string) => void }

    vm.toggleSection('湖北订单')
    await nextTick()

    expect(openTitles(wrapper).sort()).toEqual(['采购中心', '湖北订单'].sort())
  })

  it('可连续展开多个分组，已展开的不会被收起', async () => {
    const { wrapper } = await setup('/purchase')
    const vm = wrapper.vm as unknown as { toggleSection: (t: string) => void }

    // 初始已展开「采购中心」；依次再展开其余四个分组
    expect(openTitles(wrapper)).toEqual(['采购中心'])

    for (const title of ALL_TITLES.filter((t) => t !== '采购中心')) {
      vm.toggleSection(title)
      await nextTick()
      // 每展开一个新分组，「采购中心」都必须保持展开
      expect(openTitles(wrapper)).toContain('采购中心')
    }

    expect(openTitles(wrapper).sort()).toEqual([...ALL_TITLES].sort())
  })

  it('重复点击同一分组可单独收起，不影响其它分组', async () => {
    const { wrapper } = await setup('/purchase')
    const vm = wrapper.vm as unknown as { toggleSection: (t: string) => void }

    vm.toggleSection('湖北订单')
    await nextTick()
    expect(openTitles(wrapper)).toContain('湖北订单')

    vm.toggleSection('湖北订单')
    await nextTick()
    expect(openTitles(wrapper)).not.toContain('湖北订单')
    expect(openTitles(wrapper)).toContain('采购中心')
  })

  it('路由切换只补开目标分组，已手动展开的分组保持展开', async () => {
    const { wrapper, router } = await setup('/purchase')
    const vm = wrapper.vm as unknown as { toggleSection: (t: string) => void }

    vm.toggleSection('核心业务')
    await nextTick()
    expect(openTitles(wrapper).sort()).toEqual(['采购中心', '核心业务'].sort())

    await router.push('/hubei-orders')
    await nextTick()

    expect(openTitles(wrapper).sort()).toEqual(['采购中心', '核心业务', '湖北订单'].sort())
  })
})

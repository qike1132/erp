/** F5-2：当前路由不属于任何 tab 时，不得兜底高亮第一个 tab。 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'

import MobileTabBar from '@/mobile/layouts/components/MobileTabBar.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/m/home', component: { template: '<div />' } },
      { path: '/m/quick', component: { template: '<div />' } },
    ],
  })
}

describe('MobileTabBar active 兜底', () => {
  it('无匹配 tab 时不激活任何项', async () => {
    const router = makeRouter()
    await router.push('/m/quick')
    await router.isReady()
    const wrapper = mount(MobileTabBar, {
      props: { tabs: [{ name: 'home', label: '首页', icon: h('i'), to: '/m/home' }] },
      global: { plugins: [router] },
    })

    expect(wrapper.find('.m-tabbar-item').classes()).not.toContain('active')
    expect(wrapper.find('.m-tabbar-item').attributes('aria-selected')).toBe('false')
  })
})

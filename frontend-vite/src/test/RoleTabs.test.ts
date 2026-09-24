import { describe, it, expect, afterEach, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import RoleTabs from '@/views/pattern-room/components/RoleTabs.vue'
import type { RoleBrief } from '@/api/patternRoom'

function makeRole(id: number, roleName: string, isDefault = false): RoleBrief {
  return {
    id,
    project_id: 1,
    role_name: roleName,
    sort_order: id,
    is_default: isDefault,
    current_version: 'v1',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    version: 1,
  }
}

const ROLES: RoleBrief[] = [makeRole(1, '默认', true), makeRole(2, '黄蛋')]

let wrapper: VueWrapper | null = null

function mountTabs(canManage = true) {
  wrapper = mount(RoleTabs, {
    props: { roles: ROLES, currentRoleId: 1, canManage },
    attachTo: document.body,
  })
  return wrapper
}

/** 取第 index 个角色标签（显式断言存在，避免索引访问的类型空洞） */
function tabAt(w: VueWrapper, index: number) {
  const tab = w.findAll('.role-tab')[index]
  if (!tab) throw new Error(`角色标签缺失: index=${index}`)
  return tab
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('RoleTabs 删除入口（右键菜单）', () => {
  it('标签上不再渲染删除按钮，避免切换角色时误删', () => {
    const w = mountTabs()
    expect(w.findAll('.role-tab')).toHaveLength(2)
    expect(w.find('.role-tab-close').exists()).toBe(false)
  })

  it('左键点击标签只切换角色，不触发删除', async () => {
    const w = mountTabs()
    await tabAt(w, 1).trigger('click')
    expect(w.emitted('select')).toEqual([[2]])
    expect(w.emitted('remove')).toBeUndefined()
  })

  it('右键非默认角色标签弹出菜单，点击菜单项 emit remove', async () => {
    const w = mountTabs()
    expect(w.find('.role-tab-menu').exists()).toBe(false)

    await tabAt(w, 1).trigger('contextmenu')

    const menu = w.find('.role-tab-menu')
    expect(menu.exists()).toBe(true)
    expect(menu.attributes('role')).toBe('menu')
    expect(w.find('.role-tab-menu-item').attributes('role')).toBe('menuitem')
    expect(w.find('.role-tab-menu-item').text()).toContain('删除角色')

    await w.find('.role-tab-menu-item').trigger('click')
    expect(w.find('.role-tab-menu').exists()).toBe(false)
    expect(w.emitted('remove')).toEqual([[ROLES[1]]])
  })

  it('右键默认角色标签不接管浏览器原生菜单', async () => {
    const w = mountTabs()
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
    tabAt(w, 0).element.dispatchEvent(event)
    await nextTick()

    expect(event.defaultPrevented).toBe(false)
    expect(w.find('.role-tab-menu').exists()).toBe(false)
  })

  it('无管理权限时不弹菜单', async () => {
    const w = mountTabs(false)
    await tabAt(w, 1).trigger('contextmenu')
    expect(w.find('.role-tab-menu').exists()).toBe(false)
    expect(w.emitted('remove')).toBeUndefined()
  })

  it('Shift+F10 打开菜单后焦点落在菜单项，Esc 关闭并归还焦点', async () => {
    const w = mountTabs()
    const tab = tabAt(w, 1)

    await tab.trigger('keydown', { key: 'F10', shiftKey: true })

    const item = w.find('.role-tab-menu-item')
    expect(item.exists()).toBe(true)
    expect(document.activeElement).toBe(item.element)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()

    expect(w.find('.role-tab-menu').exists()).toBe(false)
    expect(document.activeElement).toBe(tab.element)
  })
})

describe('RoleTabs 右键菜单健壮性', () => {
  it('窗口尺寸变化时关闭菜单，避免菜单与标签错位', async () => {
    const w = mountTabs()
    await tabAt(w, 1).trigger('contextmenu')
    expect(w.find('.role-tab-menu').exists()).toBe(true)

    window.dispatchEvent(new Event('resize'))
    await nextTick()

    expect(w.find('.role-tab-menu').exists()).toBe(false)
  })

  it('滚动时关闭菜单（键盘翻页滚动同样触发）', async () => {
    const w = mountTabs()
    await tabAt(w, 1).trigger('contextmenu')
    expect(w.find('.role-tab-menu').exists()).toBe(true)

    window.dispatchEvent(new Event('scroll'))
    await nextTick()

    expect(w.find('.role-tab-menu').exists()).toBe(false)
  })

  it('视口小于菜单尺寸时坐标兜底为 8px，不出现负坐标', async () => {
    // 宽 100 < 菜单宽 148、高 40 < 菜单高 42：朴素的 min 计算会得出负坐标
    const innerWidth = vi.spyOn(window, 'innerWidth', 'get').mockReturnValue(100)
    const innerHeight = vi.spyOn(window, 'innerHeight', 'get').mockReturnValue(40)
    try {
      const w = mountTabs()
      await tabAt(w, 1).trigger('contextmenu', { clientX: 500, clientY: 500 })

      const style = w.find('.role-tab-menu').attributes('style') ?? ''
      expect(style).toContain('left: 8px')
      expect(style).toContain('top: 8px')
    } finally {
      innerWidth.mockRestore()
      innerHeight.mockRestore()
    }
  })

  it('菜单打开期间角色已被移除时，点击菜单项不再 emit remove', async () => {
    const w = mountTabs()
    await tabAt(w, 1).trigger('contextmenu')
    expect(w.find('.role-tab-menu').exists()).toBe(true)

    await w.setProps({ roles: ROLES.slice(0, 1) })
    await w.find('.role-tab-menu-item').trigger('click')

    expect(w.find('.role-tab-menu').exists()).toBe(false)
    expect(w.emitted('remove')).toBeUndefined()
  })
})

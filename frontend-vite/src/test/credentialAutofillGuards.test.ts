/**
 * 浏览器凭据自动填充防护回归
 *
 * 背景（2026-10-09 用户报告）：在 /user 点「编辑」后，左侧导航的菜单搜索框里被
 * 自动填入了 `admin`。排查确认应用侧无写入方（`useSidebarNav().searchQuery` 是
 * 组件内局部 ref，无任何外部赋值），因此是浏览器凭据自动填充（Chrome/Edge 密码
 * 管理器）把本站保存的用户名灌进了页面上第一个「无标记」文本框。
 *
 * 触发链：
 *   1. 「添加新用户」表单是裸的 username + password 组合、且无任何 autocomplete
 *      提示 → 浏览器把它当成登录表单，为本站保存的凭据（admin）建立填充目标；
 *   2. 「编辑用户」弹窗只有密码框、没有用户名框，且同样无提示 → 浏览器找不到
 *      与之配对的用户名框，退化为取文档中第一个文本输入框 = 侧边栏菜单搜索框；
 *   3. 于是「点编辑」这个动作让弹窗里的密码框进入 DOM，触发浏览器重新扫描并
 *      把 `admin` 填进了侧边栏搜索框。
 *
 * 防护：给这几个输入框补上明确的 autocomplete 语义 —— 密码框标 `new-password`
 * （浏览器据此判定为「设置新密码」而非登录，不再填充已保存凭据），搜索框标
 * `off` 并给一个与凭据无关的 name（永不作为用户名候选）。
 * 本文件钉住这几处标记，防止日后被「顺手删掉未使用属性」而回归。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@tanstack/vue-query', () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }))
vi.mock('@/api', () => ({
  userApi: { create: vi.fn(), update: vi.fn(), list: vi.fn(), toggle: vi.fn(), delete: vi.fn() },
}))
// 用户组件经 useUserManagement 间接引入 auth store（→ queryClient → 真实 QueryClient），
// 这里挡掉，免得为了取几个常量把整个 store 拉起来
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ navSections: [], filteredNavSections: [] }),
}))

import SidebarSearch from '@/layouts/components/SidebarSearch.vue'
import UserEditDialog from '@/views/user/components/UserEditDialog.vue'
import UserCreateForm from '@/views/user/components/UserCreateForm.vue'

/** 编辑弹窗依赖的 UiDialog 只负责透传插槽，测试里不需要真实弹层 */
const DIALOG_STUB = {
  props: ['title', 'open'],
  emits: ['update:open'],
  template: '<div class="ui-dialog"><slot /><slot name="footer" /></div>',
}

describe('浏览器凭据自动填充防护', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('侧边栏菜单搜索框', () => {
    it('SidebarSearch 的搜索框不得成为凭据填充目标', () => {
      const wrapper = mount(SidebarSearch, { props: { modelValue: '' } })
      const input = wrapper.find('input')
      expect(input.exists()).toBe(true)
      // 无 autocomplete 标记的裸文本框会被浏览器当成用户名候选
      expect(input.attributes('autocomplete')).toBe('off')
      expect(input.attributes('name')).toBeTruthy()
    })
  })

  describe('用户管理页的密码输入框', () => {
    it('编辑用户弹窗的密码框标为 new-password（不再触发登录凭据填充）', () => {
      const wrapper = mount(UserEditDialog, {
        props: { open: true, editTargetId: 1, editTargetName: 'admin', initialFactory: '' },
        global: { stubs: { UiDialog: DIALOG_STUB } },
      })
      const pwd = wrapper.find('input[type="password"]')
      expect(pwd.exists()).toBe(true)
      expect(pwd.attributes('autocomplete')).toBe('new-password')
    })

    it('添加新用户表单的用户名框与密码框都带标记，避免被识别为登录表单', () => {
      const wrapper = mount(UserCreateForm, {
        global: { stubs: { UiCheckbox: true } },
      })
      const username = wrapper
        .findAll('input')
        .find((i) => i.attributes('placeholder') === '请输入用户名')
      expect(username).toBeTruthy()
      expect(username!.attributes('autocomplete')).toBe('off')

      const pwd = wrapper.find('input[type="password"]')
      expect(pwd.exists()).toBe(true)
      expect(pwd.attributes('autocomplete')).toBe('new-password')
    })
  })
})

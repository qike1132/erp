/**
 * 板房搜索零结果空态回归（缺陷 #2）
 *
 * 拦哪种错：搜索框是**服务端**关键词过滤（序列号/产品名/版师名），零结果时旧模板
 * 一律渲染「暂无打样项目 + 点击上方『新建打样』创建第一个项目」，把「关键词没打中」
 * 误报成「库里有没数据」，引导用户重复建单。修复后带关键词的空态必须渲染
 * 「没有匹配的打样项目」，且**不含**新建 CTA 文案。
 *
 * 反向断言（第二条用例）保证修复没把真正的空库态一起改掉：
 * 没有关键词时仍应显示「暂无打样项目」并引导新建。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import CustomerGroupList from '@/views/pattern-room/components/CustomerGroupList.vue'

/** 组件所需的最小 props（空结果 + 非加载态） */
function mountList(keyword: string) {
  return mount(CustomerGroupList, {
    props: {
      groups: [],
      loading: false,
      hasData: false,
      keyword,
      selectedProjectId: null,
      canManage: true,
      statusFilter: 'in_progress' as const,
      groupPage: 1,
      groupPages: 1,
      groupTotal: 0,
    },
  })
}

describe('板房搜索零结果空态', () => {
  it('有 keyword 且零结果：渲染「无匹配」文案，且不含新建第一个项目 CTA', () => {
    const wrapper = mountList('张师傅')
    const text = wrapper.text()

    expect(text).toContain('没有匹配的打样项目')
    // CTA 文案只在「一条数据都没有」时出现，搜索态绝不能引导新建
    expect(text).not.toContain('暂无打样项目')
    expect(text).not.toContain('创建第一个项目')
  })

  it('无 keyword 的真空库：仍渲染「暂无打样项目」并引导新建（防回归）', () => {
    const wrapper = mountList('')
    const text = wrapper.text()

    expect(text).toContain('暂无打样项目')
    expect(text).toContain('创建第一个项目')
    expect(text).not.toContain('没有匹配的打样项目')
  })
})

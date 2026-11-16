/**
 * 未收录图标的兜底渲染（2026-11-16 上线前审计 Low）。
 *
 * 缺陷链：fontAwesomeLoader.loadIcon 对未收录名 `return Promise.resolve(null)`（不 reject），
 * 而 FontAwesomeIconLazy 只在 `.catch` 里回退 'fas','circle' —— null 走了 then 分支，被当成
 * 「已就绪」渲染成空白 svg。页面缺图标、无任何报错、无人知道是哪一步错了。
 *
 * 修复（两条一起才成立）：
 *  1) 组件把 null 也归到回退分支（与 catch 同一处理）；
 *  2) 回退前先 loadIcon('circle') 把兜底图标注册进 library —— 否则 vue-fontawesome 查库
 *     落空，'fas','circle' 同样渲染成空 svg，等于换个名字继续空白；
 *  3) dev 环境 loadIcon 对未收录名 warn 一次（生产 esbuild drop console）。
 *
 * 断言用渲染结果（svg 的 data-icon）而非组件内部状态：空白元素是本缺陷的可见症状。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { loadIcon, resetIconLoaderForTest } from '@/utils/fontAwesomeLoader'
import { FontAwesomeIconLazy } from '@/components/icon/FontAwesomeIconLazy'

afterEach(() => {
  resetIconLoaderForTest()
  vi.restoreAllMocks()
})

describe('未收录图标名的兜底', () => {
  it('loadIcon 仍返回 null（查不到是事实），但组件渲染兜底圆点而不是空元素', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    // 前提：loader 层语义不变，仍是 null（组件据此判断回退，不靠异常）
    await expect(loadIcon('not-exist')).resolves.toBeNull()

    const w = mount(FontAwesomeIconLazy, {
      props: { icon: 'fas fa-not-exist' },
      // 全局测试配置默认 stub 掉 FontAwesomeIcon，这里放开以验证真实渲染
      global: { stubs: { FontAwesomeIcon: false } },
    })
    await vi.waitFor(() => {
      expect(w.find('svg').exists()).toBe(true)
    })
    expect(w.find('svg').attributes('data-icon')).toBe('circle')
    w.unmount()
    expect(warn).toHaveBeenCalled()
  })

  it('dev 环境对同一未收录名只 warn 一次（图标名由渲染反复触发时不刷屏）', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await loadIcon('not-exist')
    await loadIcon('not-exist')
    await loadIcon('fas fa-not-exist') // 带前缀写法归一后同名，同样不该再报

    const hits = warn.mock.calls.filter((c) => String(c[0]).includes('图标未收录'))
    expect(hits).toHaveLength(1)
    // 告警要能定位是哪个名字，别只报「有图标找不到」
    expect(String(hits[0]![0])).toContain('not-exist')
  })
})

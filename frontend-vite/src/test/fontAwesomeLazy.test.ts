/**
 * FontAwesome 懒加载回归测试（替代已删除的 src/icons.ts 全量注册）：
 * - 字符串图标名首次出现时按需动态 import 并注册到 library；
 * - FA5 旧名（times / edit / search …）必须经 aliasToCanonical 映射后加载，
 *   否则库为空时 parse.icon 不会自动改名，首次渲染会得到空白图标；
 * - 切到懒加载后补齐的 4 个图标可解析（此前走 icons.ts 时也缺失）；
 * - 未收录图标安全返回 null，不抛错；
 * - <FontAwesomeIconLazy> 异步加载完成后渲染 svg，加载中不输出空节点；
 * - 完整 IconDefinition 对象直接透传渲染；
 * - useToast 的主题图标同样走懒加载，不再静态引入整套图标。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { findIconDefinition, type IconLookup } from '@fortawesome/fontawesome-svg-core'
import { loadIcon, canonicalIconName, iconLoaders, resetIconLoaderForTest } from '@/utils/fontAwesomeLoader'
import { FontAwesomeIconLazy } from '@/components/icon/FontAwesomeIconLazy'
import { showToast } from '@/composables/useToast'

/** 按 'fas' + kebab 名查库；kebab 名不在 TS 的 IconName 字面量联合里，故收窄断言。 */
function libraryHas(name: string): boolean {
  return !!findIconDefinition({ prefix: 'fas', iconName: name } as IconLookup)
}

// library 是模块级单例，用例间共享。下方「全清单加载」用例会把所有图标注册进库，
// 这会破坏依赖「加载前 library 为空」的后续用例（渲染前不输出节点），
// 故每个用例结束后把 library 与 pending 缓存复位到初始态。
afterEach(() => {
  resetIconLoaderForTest()
})

describe('fontAwesomeLoader 懒加载清单', () => {
  it('loadIcon 动态导入并注册图标到 library', async () => {
    const def = await loadIcon('cart-shopping')
    expect(def).toBeTruthy()
    expect(libraryHas('cart-shopping')).toBe(true)
  })

  it('FA5 旧名映射到 FA6 canonical 名', () => {
    expect(canonicalIconName('sync-alt')).toBe('arrows-rotate')
    expect(canonicalIconName('check-circle')).toBe('circle-check')
    expect(canonicalIconName('exclamation-triangle')).toBe('triangle-exclamation')
  })

  // 带样式前缀的 FA5 写法（'fas fa-inbox'）在 UiEmpty / iconMap / 侧边栏随处可见；
  // 不剥前缀时查 loaders 必落空 → loadIcon 返回 null → 空态图标整个不渲染。
  it.each([
    ['fas fa-inbox', 'inbox'],
    ['far fa-inbox', 'inbox'],
    ['fab fa-inbox', 'inbox'],
    ['fa-inbox', 'inbox'],
  ])('带前缀写法 %s 归一到裸名 %s', (prefixed, bare) => {
    expect(canonicalIconName(prefixed)).toBe(canonicalIconName(bare))
  })

  it("'fas fa-times' 前缀 + 旧别名都归一到 xmark，两种写法加载出同一图标", async () => {
    const fromPrefixed = await loadIcon('fas fa-times')
    const fromBare = await loadIcon('times')
    expect(fromPrefixed).toBeTruthy()
    expect(fromBare).toBeTruthy()
    expect(fromPrefixed!.iconName).toBe(fromBare!.iconName)
    expect(fromPrefixed!.iconName).toBe('xmark')
  })

  it('未知名（带不带前缀）仍返回 null，不抛错', async () => {
    await expect(loadIcon('definitely-not-an-icon')).resolves.toBeNull()
    await expect(loadIcon('fas fa-definitely-not-an-icon')).resolves.toBeNull()
  })

  // 这些旧名在模板里随处可见；库为空时 parse.icon 不会自动改名，
  // 必须靠 aliasToCanonical 兜底，否则首次渲染会得到空白图标。
  it.each([
    ['archive', 'box-archive'],
    ['boxes', 'boxes-stacked'],
    ['cog', 'gear'],
    ['cogs', 'gears'],
    ['edit', 'pen-to-square'],
    ['file-archive', 'file-zipper'],
    ['history', 'clock-rotate-left'],
    ['magic', 'wand-magic'],
    ['redo', 'arrow-rotate-right'],
    ['save', 'floppy-disk'],
    ['search', 'magnifying-glass'],
    ['times', 'xmark'],
    ['tshirt', 'shirt'],
  ])('FA5 旧名 %s 映射到 %s 且可加载', async (legacy, canonical) => {
    expect(canonicalIconName(legacy)).toBe(canonical)
    await expect(loadIcon(legacy)).resolves.toBeTruthy()
    expect(libraryHas(canonical)).toBe(true)
  })

  // 期望清单直接从 loaders 推导：往清单里新增一条 loader 而图标解析不了时，
  // 这里立刻红 —— 固定清单（旧的 ['envelope-open-text', 'globe', ...]）永远测不到新条目。
  it('清单里每个图标都能解析并注册（覆盖所有 loaders 条目）', async () => {
    for (const name of Object.keys(iconLoaders)) {
      const def = await loadIcon(name)
      expect(def, `loaders['${name}'] 应解析出 IconDefinition`).toBeTruthy()
      expect(libraryHas(name), `loaders['${name}'] 应注册进 library`).toBe(true)
    }
    // 至少确认清单非空（防止 loaders 被清空后测试静默通过）
    expect(Object.keys(iconLoaders).length).toBeGreaterThan(100)
  })

  it('旧清单时代补齐的 4 个图标仍可解析（抽样锚点）', async () => {
    for (const name of ['envelope-open-text', 'globe', 'keyboard', 'rotate-right']) {
      const def = await loadIcon(name)
      expect(def).toBeTruthy()
      expect(libraryHas(name)).toBe(true)
    }
  })

  it('未收录图标返回 null，不抛错', async () => {
    await expect(loadIcon('definitely-not-an-icon')).resolves.toBeNull()
  })
})

describe('FontAwesomeIconLazy 组件', () => {
  it('字符串图标在异步加载完成后渲染出 svg', async () => {
    const w = mount(FontAwesomeIconLazy, {
      props: { icon: 'fas fa-plus' },
      // 全局测试配置默认 stub 掉 FontAwesomeIcon，这里放开以验证真实渲染
      global: { stubs: { FontAwesomeIcon: false } },
    })
    await vi.waitFor(() => {
      expect(w.find('svg').exists()).toBe(true)
    })
    w.unmount()
  })

  it('渲染前不输出节点（避免闪出空图标）', () => {
    const w = mount(FontAwesomeIconLazy, { props: { icon: 'fas fa-barcode' } })
    expect(w.html()).toBe('')
    w.unmount()
  })

  it('完整 IconDefinition 对象直接透传渲染', async () => {
    const { faTruck } = await import('@fortawesome/free-solid-svg-icons/faTruck')
    const w = mount(FontAwesomeIconLazy, {
      props: { icon: faTruck },
      global: { stubs: { FontAwesomeIcon: false } },
    })
    await vi.waitFor(() => {
      expect(w.find('svg').exists()).toBe(true)
    })
    w.unmount()
  })

  it('FA5 旧名（fas fa-times）也能渲染出 svg', async () => {
    const w = mount(FontAwesomeIconLazy, {
      props: { icon: 'fas fa-times' },
      global: { stubs: { FontAwesomeIcon: false } },
    })
    await vi.waitFor(() => {
      expect(w.find('svg').exists()).toBe(true)
    })
    w.unmount()
  })
})

describe('useToast 图标懒加载', () => {
  it('toast 主题图标按需加载后渲染为 svg', async () => {
    showToast('图标懒加载测试', 'success', { duration: 60000 })
    await vi.waitFor(() => {
      const container = document.getElementById('__toast_container__')
      expect(container?.querySelector('svg')).toBeTruthy()
    })
    document.getElementById('__toast_container__')?.remove()
  })
})

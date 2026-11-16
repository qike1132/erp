/**
 * 导航图标清单 = 种子脚本 ∪ 前端解析器（2026-11-16 上线前审计 Low，防回归）。
 *
 * 背景：左侧导航的图标来自数据库 permission.icon（由 scripts/seed_nav.py 等种子脚本写入），
 * 前端拿到名字后要走 canonicalIconName → aliasToCanonical → fontAwesomeLoader 的 loaders
 * 才能渲染出来。两侧各改各的：种子脚本里写了一个 loaders 没收录、别名表也没映射的名字，
 * 页面不报错、只是那颗图标静默变成兜底圆点（甚至空白，见第 6 条同类缺陷）。
 * 现状 0 现网命中，所以这是一条纯防回归的守卫：谁往种子脚本里加新图标名，这里立刻红。
 *
 * 为什么**读脚本**而不是硬编码快照：硬编码的清单与 Python 侧是两个真相源，脚本改了清单
 * 不会跟着变，守卫就退化成「昨天的副本自测」。文件用 `new URL` 之外的 dirname 相对定位，
 * 不依赖 vitest 的 cwd（从 src/test 往上三级 = 仓库根）。
 *
 * 实测口径：`scripts/*nav*.py`（含 seed_nav.py 自身）里 icon= / 'icon': 形式的名字去重后
 * 23 个——seed_nav.py 21 个 + add_/fix_ 一次性脚本里的 fa-calendar-alt、fa-shield-alt。
 * 审计记录的 22 个是把 seed 之外脚本只算了一个的口径差异，不改变结论：它们都必须可解析。
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mount } from '@vue/test-utils'
import { loadIcon, resetIconLoaderForTest } from '@/utils/fontAwesomeLoader'
import { FontAwesomeIconLazy } from '@/components/icon/FontAwesomeIconLazy'

const here = dirname(fileURLToPath(import.meta.url)) // frontend-vite/src/test
const scriptsDir = resolve(here, '..', '..', '..', 'scripts')

/**
 * 抽出所有导航种子脚本里的图标名。
 *
 * 只认 `icon='fa-x'` / `icon = 'fa-x'` / `'icon': 'fa-x'` 这三种真实写法（种子脚本里图标
 * 一定挂在 icon 键上）：退化成裸 `fa-` 全局匹配会把 CSS 类名、注释里的名字一起抓进来，
 * 让守卫对着不存在于种子的名字报红。
 */
function seedIconNames(): string[] {
  const files = readdirSync(scriptsDir).filter((f) => f.endsWith('.py') && f.includes('nav'))
  const names = new Set<string>()
  for (const file of files) {
    const text = readFileSync(join(scriptsDir, file), 'utf-8')
    for (const match of text.matchAll(/icon\s*['"]?\s*[:=]\s*['"](fa-[a-z0-9-]+)['"]/g)) {
      // noUncheckedIndexedAccess: [1] 是 string | undefined，捕获组必然存在，非空断言只修类型层
      names.add(match[1]!)
    }
  }
  return [...names].sort()
}

const SEED_ICONS = seedIconNames()

afterEach(() => {
  resetIconLoaderForTest()
  vi.restoreAllMocks()
})

describe('导航种子脚本的图标名都能被前端解析', () => {
  it('清单非空且含种子脚本里的锚点图标（正则失效时不许静默通过）', () => {
    expect(SEED_ICONS.length).toBeGreaterThanOrEqual(20)
    expect(SEED_ICONS).toContain('fa-warehouse') // seed_nav.py: 总订单
    expect(SEED_ICONS).toContain('fa-database') // seed_nav.py: 数据备份
  })

  it.each(SEED_ICONS)('%s 可被 loaders/别名表解析（不可解析=侧边栏静默无图标）', async (name) => {
    const def = await loadIcon(name)
    expect(def, `${name} 应解析出 IconDefinition；请在 fontAwesomeLoader 的 loaders/aliasToCanonical 补登记`).toBeTruthy()
  })

  it('清单外的图标名渲染成兜底圆点（与未收录图标的兜底口径呼应，不是空白）', async () => {
    const outside = 'fa-not-in-nav-seed'
    expect(SEED_ICONS).not.toContain(outside)
    // 未收录名在 dev 会 warn（第 6 条修复），这里静音避免测试输出噪音
    vi.spyOn(console, 'warn').mockImplementation(() => {})

    const w = mount(FontAwesomeIconLazy, {
      props: { icon: outside },
      global: { stubs: { FontAwesomeIcon: false } },
    })
    await vi.waitFor(() => {
      expect(w.find('svg').exists()).toBe(true)
    })
    expect(w.find('svg').attributes('data-icon')).toBe('circle')
    w.unmount()
  })
})

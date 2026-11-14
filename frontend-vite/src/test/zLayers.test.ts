/**
 * Z 层级不变量：应用自己的「盖在 PrimeVue 浮层之上」的那些层，必须真的超过 PrimeVue 的层。
 *
 * 背景：应用有两套 z 数值 —— app.css 的 --z-* 是 10~40 的小数，而 PrimeVue 自己的浮层由
 * main.ts 的 zIndex 配置放大到 2000/2100。抽屉（PrimeVue Drawer）的遮罩就是 2100。
 * 曾因此出事：明细抽屉里点「删除」弹出的确认框用的是 --z-modal-nested=70，远低于 2100，
 * 被遮罩压住点不到。本测试把「嵌套弹窗/Toast 必须超过 PrimeVue 的 modal 层」钉死。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function readNumber(source: string, pattern: RegExp, label: string): number {
  const m = source.match(pattern)
  if (!m) throw new Error(`未找到 ${label}`)
  return Number(m[1])
}

const appCss = readFileSync('src/styles/app.css', 'utf8')
const mainTs = readFileSync('src/main.ts', 'utf8')

const cssToken = (name: string) =>
  readNumber(appCss, new RegExp(`--${name}:\\s*(\\d+)`), `--${name}`)

describe('Z 层级不变量', () => {
  const primevueModal = readNumber(mainTs, /zIndex:\s*\{[^}]*\bmodal:\s*(\d+)/, 'main.ts zIndex.modal')

  it('嵌套弹窗层必须盖过 PrimeVue 的 modal 层（否则被抽屉遮罩压住）', () => {
    expect(cssToken('z-overlay-nested')).toBeGreaterThan(primevueModal)
    expect(cssToken('z-modal-nested')).toBeGreaterThan(primevueModal)
  })

  it('Toast 层必须盖过嵌套弹窗层', () => {
    expect(cssToken('z-toast')).toBeGreaterThan(cssToken('z-modal-nested'))
  })

  it('基础层序保持单调：overlay < modal < page-modal < overlay-nested < modal-nested', () => {
    expect(cssToken('z-overlay')).toBeLessThan(cssToken('z-modal'))
    expect(cssToken('z-modal')).toBeLessThan(cssToken('z-overlay-nested'))
    expect(cssToken('z-overlay-nested')).toBeLessThan(cssToken('z-modal-nested'))
  })

  it('页面级自定义弹窗层必须低于嵌套弹窗层（否则弹窗内确认框被遮挡）', () => {
    // BomEditor/ProductEditDialog 等的遮罩 = --z-page-modal(1050)；其内弹出的
    // UiConfirmDialog 用 --z-*-nested。若 page-modal 漂到 nested 之上，确认框
    // 又会被压住（2026-10-10 实测的事故形态）。
    expect(cssToken('z-page-modal')).toBeLessThan(cssToken('z-overlay-nested'))
    expect(cssToken('z-page-modal')).toBeLessThan(cssToken('z-modal-nested'))
  })
})

/** 递归收集层级来源：样式块之外还要算 .ts，因为内联层级（驼峰 zIndex）就写在脚本里 */
function collectSources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) collectSources(full, out)
    else if (/\.(vue|css|scss|ts)$/.test(name) && !name.endsWith('.d.ts')) out.push(full)
  }
  return out
}

/** 四种裸写层级的形式：CSS 属性、JS 键/赋值（含驼峰）、setProperty、Tailwind 任意值 */
const BARE_Z_PATTERNS = [
  /z-index\s*:\s*(-?\d+)/g,
  /\bzIndex\s*[:=]\s*['"]?(-?\d+)/g,
  /setProperty\(\s*['"]z-index['"]\s*,\s*['"]?(-?\d+)/g,
  /z-\[\s*(-?\d+)\s*\]/g,
]

/** 先剥注释再扫：注释里写「与 z-index: 2100 对齐」不应被当成真实现 */
function stripComments(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/(^|\s)\/\/[^\n]*/g, '$1')
}

/**
 * 允许继续裸写的「文件 + 值」。每加一条都要在评审里给理由；
 * 下方有反向断言要求这些值仍在，防止条目僵化后变成永久豁免。
 */
const BARE_ALLOWLIST: Record<string, number[]> = {
  // 兜底提示的出现时机就是渲染已出问题，不能反过来依赖 app.css 的变量解析。
  // 与 --z-error-fallback 同值，另有断言锁一致性。
  'src/main.ts': [10000],
  // 「透明遮罩 + 右键菜单」的同构实现，两条代码靠彼此的相对值工作，均 < --z-page-modal。
  'src/views/pattern-room/components/RoleTabs.vue': [1000, 1001],
  'src/views/product/components/BomEditor.css': [1000, 1001],
}

/** 最小全局令牌，也是「局部层叠」与「全局层」的分界线 */
const MIN_GLOBAL_TOKEN = 200

describe('Z 层级令牌化：新的层级必须走 --z-*，不得再裸写数字', () => {
  const primevueModal = readNumber(mainTs, /zIndex:\s*\{[^}]*\bmodal:\s*(\d+)/, 'main.ts zIndex.modal')
  const primevueOverlay = readNumber(mainTs, /zIndex:\s*\{[^}]*\boverlay:\s*(\d+)/, 'main.ts zIndex.overlay')

  it('外壳层低于页面级弹窗，避免导航/抽屉盖住业务弹窗', () => {
    expect(cssToken('z-shell-scrim')).toBeLessThan(cssToken('z-shell-drawer'))
    expect(cssToken('z-shell-drawer')).toBeLessThan(cssToken('z-page-modal'))
  })

  it('自绘浮层三档各自匹配其上下文，不可互相替代', () => {
    // 页面级下拉：高于外壳、刻意低于 page-modal，不会盖住随后打开的弹窗
    expect(cssToken('z-page-float')).toBeGreaterThan(cssToken('z-shell-drawer'))
    expect(cssToken('z-page-float')).toBeLessThan(cssToken('z-page-modal'))
    // 弹窗内下拉：要盖过 page-modal，但不能越过 PrimeVue（否则 PrimeVue 浮层被压）
    expect(cssToken('z-inline-float')).toBeGreaterThan(cssToken('z-page-modal'))
    expect(cssToken('z-inline-float')).toBeLessThan(primevueOverlay)
    // teleport 到 body 的自绘面板：必须严格高于 PrimeVue modal。同值(2100)时层级由
    // DOM 插入顺序决定，面板打开期间再挂一个 PrimeVue 2100 层就会反超。
    expect(cssToken('z-float-raised')).toBeGreaterThan(primevueModal)
    expect(cssToken('z-float-raised')).toBeLessThan(cssToken('z-overlay-nested'))
    // 跨上下文兜底：高于所有弹窗与 toast
    expect(cssToken('z-float-fallback')).toBeGreaterThan(cssToken('z-toast'))
  })

  it('最高三档单调：进度条 < 错误兜底 < skip-link', () => {
    expect(cssToken('z-route-progress')).toBeGreaterThan(cssToken('z-toast'))
    expect(cssToken('z-error-fallback')).toBeGreaterThan(cssToken('z-route-progress'))
    expect(cssToken('z-skip-link')).toBeGreaterThan(cssToken('z-error-fallback'))
  })

  it('局部层叠的分界线是最小全局令牌', () => {
    // 表格 sticky / 卡片浮起这类「局部值」多数不建层叠上下文，值一大会直接参与
    // 根上下文比较，跟全局层抢；守住 200 这条线即守住它们的局部性。
    expect(cssToken('z-dropdown')).toBeLessThan(MIN_GLOBAL_TOKEN)
    expect(cssToken('z-sticky')).toBeLessThan(MIN_GLOBAL_TOKEN)
    expect(cssToken('z-overlay')).toBeLessThan(MIN_GLOBAL_TOKEN)
  })

  it('错误兜底条的硬编码值与 --z-error-fallback 保持一致', () => {
    const hardcoded = readNumber(mainTs, /z-index:(\d+);background:#fee2e2/, 'main.ts 错误兜底条 z-index')
    expect(hardcoded).toBe(cssToken('z-error-fallback'))
  })

  it(`除白名单外，源码里不得出现 ≥${MIN_GLOBAL_TOKEN} 的裸层级（四种写法全查）`, () => {
    const offenders: string[] = []
    for (const file of collectSources('src')) {
      const rel = file.replace(/\\/g, '/')
      if (rel.endsWith('src/styles/app.css')) continue
      if (rel.startsWith('src/test/')) continue
      const allowed = BARE_ALLOWLIST[rel] ?? []
      const text = stripComments(readFileSync(file, 'utf8'))
      for (const pattern of BARE_Z_PATTERNS) {
        for (const m of text.matchAll(pattern)) {
          const value = Number(m[1])
          if (value >= MIN_GLOBAL_TOKEN && !allowed.includes(value)) {
            offenders.push(`${rel}: ${value}（${m[0].trim()}）`)
          }
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('白名单条目不得僵化：所列值必须仍然存在', () => {
    for (const [file, values] of Object.entries(BARE_ALLOWLIST)) {
      const text = stripComments(readFileSync(file, 'utf8'))
      const found = BARE_Z_PATTERNS.flatMap((pattern) => [...text.matchAll(pattern)].map((m) => Number(m[1])))
      for (const value of values) expect(found, `${file} 的 ${value}`).toContain(value)
    }
  })

  it('外壳组件不得把层级退回裸值（改回 200/300/9999 即变红）', () => {
    const shellFiles = [
      'src/App.vue',
      'src/layouts/DefaultLayout.vue',
      'src/layouts/components/AppSidebar.vue',
      'src/mobile/components/MBottomSheet.vue',
      'src/mobile/layouts/MobileLayout.vue',
    ]
    for (const file of shellFiles) {
      expect(readFileSync(file, 'utf8'), file).not.toMatch(/z-index:\s*(200|300|9999|99999)\s*;/)
    }
  })
})

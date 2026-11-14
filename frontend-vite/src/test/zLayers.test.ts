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

/** 递归收集样式来源：.vue 的 style 块与独立 .css/.scss 都在此列 */
function collectStyleSources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) collectStyleSources(full, out)
    else if (/\.(vue|css|scss)$/.test(name)) out.push(full)
  }
  return out
}

describe('Z 层级令牌化：新的层级必须走 --z-*，不得再裸写数字', () => {
  const primevueModal = readNumber(mainTs, /zIndex:\s*\{[^}]*\bmodal:\s*(\d+)/, 'main.ts zIndex.modal')
  const primevueOverlay = readNumber(mainTs, /zIndex:\s*\{[^}]*\boverlay:\s*(\d+)/, 'main.ts zIndex.overlay')

  it('外壳层低于页面级弹窗，避免导航/抽屉盖住业务弹窗', () => {
    expect(cssToken('z-shell-scrim')).toBeLessThan(cssToken('z-shell-drawer'))
    expect(cssToken('z-shell-drawer')).toBeLessThan(cssToken('z-page-modal'))
  })

  it('自绘浮层三档各自匹配其上下文，不可互相替代', () => {
    // 弹窗内下拉：要盖过 page-modal，但不能越过 PrimeVue（否则 PrimeVue 浮层被压）
    expect(cssToken('z-inline-float')).toBeGreaterThan(cssToken('z-page-modal'))
    expect(cssToken('z-inline-float')).toBeLessThan(primevueOverlay)
    // teleport 到 body 的自绘面板：至少与 PrimeVue modal 齐平
    expect(cssToken('z-float-raised')).toBeGreaterThanOrEqual(primevueModal)
    // 跨上下文兜底：高于所有弹窗与 toast
    expect(cssToken('z-float-fallback')).toBeGreaterThan(cssToken('z-toast'))
  })

  it('最高三档单调：进度条 < 错误兜底 < skip-link', () => {
    expect(cssToken('z-route-progress')).toBeGreaterThan(cssToken('z-toast'))
    expect(cssToken('z-error-fallback')).toBeGreaterThan(cssToken('z-route-progress'))
    expect(cssToken('z-skip-link')).toBeGreaterThan(cssToken('z-error-fallback'))
  })

  // 扫描范围只含 .vue/.css/.scss：main.ts 的错误兜底条刻意硬编码（兜底提示不能在
  // 样式系统失效时才依赖变量），这条断言负责让那处硬编码与令牌不漂移。
  it('错误兜底条的硬编码值与 --z-error-fallback 保持一致', () => {
    const hardcoded = readNumber(mainTs, /z-index:(\d+);background:#fee2e2/, 'main.ts 错误兜底条 z-index')
    expect(hardcoded).toBe(cssToken('z-error-fallback'))
  })

  // 页面内局部层叠：只在自身弹窗/滚动容器的层叠上下文里互相比较，
  // 换成全局 token 反而会与参照页漂开（见 app.css 令牌区注释）。
  const LOCAL_STACK_ALLOWLIST = [
    'src/views/pattern-room/components/RoleTabs.vue',
    'src/views/product/components/BomEditor.css',
  ]

  it('除局部层叠白名单外，源码里不得出现 ≥1000 的裸 z-index', () => {
    const offenders: string[] = []
    for (const file of collectStyleSources('src')) {
      const rel = file.replace(/\\/g, '/')
      if (rel.endsWith('src/styles/app.css')) continue
      if (LOCAL_STACK_ALLOWLIST.some((allowed) => rel.endsWith(allowed))) continue
      for (const m of readFileSync(file, 'utf8').matchAll(/z-index:\s*(-?\d+)/g)) {
        const value = Number(m[1])
        if (value >= 1000) offenders.push(`${rel}: z-index ${value}`)
      }
    }
    expect(offenders).toEqual([])
  })

  it('白名单只容纳 1000/1001 成对的局部层，不得变成新全局层的避难所', () => {
    for (const allowed of LOCAL_STACK_ALLOWLIST) {
      const values = [...readFileSync(allowed, 'utf8').matchAll(/z-index:\s*(-?\d+)/g)].map((m) => Number(m[1]))
      expect(values.length, allowed).toBeGreaterThan(0)
      for (const value of values) expect([1000, 1001], allowed).toContain(value)
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

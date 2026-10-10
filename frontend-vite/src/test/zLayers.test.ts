/**
 * Z 层级不变量：应用自己的「盖在 PrimeVue 浮层之上」的那些层，必须真的超过 PrimeVue 的层。
 *
 * 背景：应用有两套 z 数值 —— app.css 的 --z-* 是 10~40 的小数，而 PrimeVue 自己的浮层由
 * main.ts 的 zIndex 配置放大到 2000/2100。抽屉（PrimeVue Drawer）的遮罩就是 2100。
 * 曾因此出事：明细抽屉里点「删除」弹出的确认框用的是 --z-modal-nested=70，远低于 2100，
 * 被遮罩压住点不到。本测试把「嵌套弹窗/Toast 必须超过 PrimeVue 的 modal 层」钉死。
 */
import { readFileSync } from 'node:fs'
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

/**
 * PWA 预缓存的不变式守卫（2026-10-30 审计 A-M47）。
 *
 * vite.config.ts 的 workbox 里有两行**必须成对存在**：
 *   · navigateFallback: null   —— 关掉 NavigationRoute
 *   · globIgnores: ['**\/index.html'] —— 把 index.html 移出预缓存
 *
 * 只删任一行都会让 SW 重新接管 HTML：发布后用户一直看到旧界面（旧 index.html
 * 引旧入口 chunk），且无痕窗口的 SW 活到窗口组全关为止，刷新无效。
 * 原守卫只断言 `maximumFileSizeToCacheInBytes` 存在，删掉这两行 1800+ 用例全绿。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const src = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf-8')

/** 取 VitePWA 的 workbox 配置块（到 runtimeCaching 之前即可覆盖全部预缓存相关键）。 */
function workboxBlock(): string {
  const start = src.indexOf('workbox:')
  expect(start, 'vite.config.ts 必须保留 workbox 配置块').toBeGreaterThan(-1)
  const end = src.indexOf('runtimeCaching:', start)
  return src.slice(start, end === -1 ? undefined : end)
}

describe('service worker precache', () => {
  it('defers service worker registration so it cannot block HTML parsing', () => {
    expect(src).toMatch(/injectRegister\s*:\s*'script-defer'/)
  })

  it('does not let manifest icons bypass the startup precache whitelist', () => {
    expect(src).toMatch(/includeManifestIcons\s*:\s*false/)
  })

  it('caps the precached file size', () => {
    expect(src).toMatch(/maximumFileSizeToCacheInBytes\s*:/)
    expect(workboxBlock()).toMatch(/maximumFileSizeToCacheInBytes\s*:\s*2\s*\*\s*1024\s*\*\s*1024/)
  })

  it('precaches startup assets instead of every route, chart, telemetry and icon chunk', () => {
    const block = workboxBlock()
    expect(block).toMatch(/globPatterns\s*:\s*\[[\s\S]*'assets\/app-entry-\*\.js'/)
    expect(block).toMatch(/globPatterns\s*:\s*\[[\s\S]*'logo_plush\.webp'/)
    expect(block).not.toMatch(/globPatterns\s*:\s*\[\s*['"]\*\*\/\*\./)
    expect(block).not.toMatch(/'assets\/vendor-(?:echarts|fa-icons|primevue|reka-ui)-/)
  })

  it('keeps navigateFallback disabled', () => {
    expect(workboxBlock()).toMatch(/navigateFallback\s*:\s*null/)
  })

  it('keeps index.html out of the precache globs', () => {
    const block = workboxBlock()
    expect(block).toMatch(/globIgnores\s*:/)
    expect(block).toMatch(/globIgnores\s*:\s*\[[^\]]*\*\*\/index\.html/)
  })

  it('keeps the pair together (removing either line breaks navigation freshness)', () => {
    const block = workboxBlock()
    const hasFallbackOff = /navigateFallback\s*:\s*null/.test(block)
    const hasIgnore = /globIgnores\s*:\s*\[[^\]]*\*\*\/index\.html/.test(block)
    expect(
      hasFallbackOff && hasIgnore,
      'navigateFallback:null 与 globIgnores:**/index.html 必须成对存在，缺一即让 SW 重新接管 HTML',
    ).toBe(true)
  })
})

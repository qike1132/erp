/**
 * check-css-legacy.mjs — 构建后自检：产物 CSS 里不得再出现 `@layer` / `oklch(`。
 *
 * 背景：旧内核（Chrome < 99）不认识 `@layer` at-rule，会**整块跳过**（未知 at-rule 连同
 * 内容一起忽略）。Tailwind v4 的产物全部包在 `@layer` 里，于是整张样式表被丢弃、页面
 * 退化成无样式。去掉层靠 postcss.config.mjs 里的解包插件；本脚本防止它失效（例如
 * `@tailwindcss/vite` 与 `vite:css` 的插件顺序变化）后**静默回归**。
 *
 * `oklch(`：Chrome < 111 不支持，Tailwind v4 默认调色板大量使用；postcss 解包插件
 * 同样负责降级为 rgb。漏检会导致旧内核上**颜色全部失效**（复核 2026-10-11 N6）。
 *
 * 用法：node scripts/check-css-legacy.mjs [distDir]   默认 dist
 * 退出码：0 = 通过；1 = 发现 `@layer` 或 `oklch(`。
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const root = process.argv[2] ?? 'dist'

if (!existsSync(root)) {
  console.error(`[check-css-legacy] 目录不存在：${root}（先构建）`)
  process.exit(1)
}

const offenders = []
function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p)
    else if (name.endsWith('.css')) {
      const css = readFileSync(p, 'utf8')
      const layerHits = (css.match(/@layer\b/g) || []).length
      const oklchHits = (css.match(/oklch\(/g) || []).length
      if (layerHits || oklchHits) offenders.push(`${p}（@layer ${layerHits} 处 / oklch( ${oklchHits} 处）`)
    }
  }
}
walk(root)

if (offenders.length) {
  console.error('[check-css-legacy] ❌ 产物 CSS 仍含 @layer / oklch(（旧内核会整块跳过 → 样式全丢/颜色失效）：')
  for (const o of offenders) console.error('  - ' + o)
  console.error(
    '[check-css-legacy] 多半是 postcss.config.mjs 的解包插件没生效 —— 检查 @tailwindcss/vite 与 vite:css 的插件顺序',
  )
  process.exit(1)
}
console.log(`[check-css-legacy] ✓ ${root} 下 CSS 已无 @layer / oklch(`)

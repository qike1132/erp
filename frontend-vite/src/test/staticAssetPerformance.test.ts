import { readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const loginViews = [
  'src/views/login/components/LoginBrandSection.vue',
  'src/mobile/views/login/MLoginView.vue',
]

describe('first-screen logo delivery', () => {
  it('uses the small favicon instead of downloading the full-size brand image twice', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf-8')
    expect(html).toContain('<link rel="icon" type="image/png" href="/favicon.png" />')
    expect(html).not.toContain('<link rel="icon" type="image/png" href="/logo_plush.png" />')
  })

  it.each(loginViews)('uses a lossless WebP candidate and eagerly discovers the above-fold logo in %s', (file) => {
    const src = readFileSync(resolve(process.cwd(), file), 'utf-8')
    expect(src).toContain('/logo_plush-256.webp 256w, /logo_plush.webp 512w')
    expect(src).toContain('type="image/webp"')
    expect(src).toMatch(/<img[^>]+fetchpriority="high"/)
    expect(src).not.toMatch(/<img[^>]+loading="lazy"/)
  })

  it('keeps the WebP smaller than the pixel-identical PNG fallback', () => {
    const smallWebp = statSync(resolve(process.cwd(), 'public/logo_plush-256.webp')).size
    const webp = statSync(resolve(process.cwd(), 'public/logo_plush.webp')).size
    const png = statSync(resolve(process.cwd(), 'public/logo_plush.png')).size
    expect(smallWebp).toBeLessThan(webp)
    expect(webp).toBeLessThan(png)
  })

  it('allows short-lived HTTP caching with revalidation for both logo formats', () => {
    const nginx = readFileSync(resolve(process.cwd(), '../config/nginx-windows.conf'), 'utf-8')
    for (const file of ['logo_plush.webp', 'logo_plush-256.webp', 'logo_plush.png']) {
      const start = nginx.indexOf(`location = /${file} {`)
      expect(start).toBeGreaterThan(-1)
      const block = nginx.slice(start, nginx.indexOf('}', start))
      expect(block).toContain('Cache-Control "public, max-age=3600, must-revalidate"')
    }
  })
})

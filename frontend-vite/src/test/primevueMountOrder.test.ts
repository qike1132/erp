import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('main.ts mount order', () => {
  it('installs PrimeVue before mounting the app', () => {
    // vitest 以 frontend-vite 为 cwd 运行
    const src = readFileSync(resolve(process.cwd(), 'src/main.ts'), 'utf-8')
    const install = src.indexOf("import('primevue/config')")
    const mount = src.indexOf("app.mount('#app')")
    expect(install).toBeGreaterThan(-1)
    expect(mount).toBeGreaterThan(-1)
    expect(install).toBeLessThan(mount)
  })

  it('loads the independent PrimeVue config and passthrough styles in parallel', () => {
    const src = readFileSync(resolve(process.cwd(), 'src/main.ts'), 'utf-8')
    expect(src).toMatch(/Promise\.all\(\[[\s\S]*import\('primevue\/config'\)[\s\S]*import\('\.\/styles\/primevue-pt'\)/)
  })
})

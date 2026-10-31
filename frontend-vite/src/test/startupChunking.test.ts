import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const src = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf-8')
const outputBlock = src.slice(src.indexOf('output:'), src.indexOf('server:'))

describe('startup chunk boundaries', () => {
  it('does not force every on-demand PrimeVue or Reka UI component into one eager vendor chunk', () => {
    expect(outputBlock).not.toMatch(/'vendor-primevue'\s*:/)
    expect(outputBlock).not.toMatch(/'vendor-reka-ui'\s*:/)
  })

  it('does not force every lazy FontAwesome definition into the first icon request', () => {
    expect(outputBlock).not.toMatch(/'vendor-fa-icons'\s*:/)
  })

  it('gives the main entry a distinct name for the SW startup precache whitelist', () => {
    expect(outputBlock).toMatch(/entryFileNames\s*\(chunk\)/)
    expect(outputBlock).toMatch(/chunk\.name\s*===\s*'index'\s*\?\s*'assets\/app-entry-\[hash\]\.js'/)
  })
})

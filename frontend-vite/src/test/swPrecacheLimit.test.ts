import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('service worker precache', () => {
  it('caps the precached file size', () => {
    const src = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf-8')
    expect(src).toMatch(/maximumFileSizeToCacheInBytes\s*:/)
  })
})

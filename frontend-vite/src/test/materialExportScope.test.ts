/** P1-25：来料进度/历史两个导出按钮必须传不同 scope。 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// vitest 的 root 是 frontend-vite，直接按仓内相对路径读取
const source = readFileSync('src/views/material/MaterialView.vue', 'utf-8')

describe('来料导出 tab 口径', () => {
  it('进度导出传 scope=progress、历史导出传 scope=history', () => {
    expect(source).toMatch(/materialApi\.export\(\{\s*scope:\s*'progress'\s*\}/)
    expect(source).toMatch(/materialApi\.export\(\{\s*scope:\s*'history'\s*\}/)
  })
})

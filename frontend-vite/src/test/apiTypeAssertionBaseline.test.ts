import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const src = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function walk(dir: string, acc: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    const full = join(dir, e)
    if (statSync(full).isDirectory()) { if (e !== 'test') walk(full, acc) }
    else if (/\.(ts|vue)$/.test(e)) acc.push(full)
  }
  return acc
}

export function countAssertions(): number {
  let n = 0
  for (const f of walk(src)) {
    const text = readFileSync(f, 'utf-8')
    n += (text.match(/as unknown as/g) ?? []).length
  }
  return n
}

describe('as unknown as 断言基线', () => {
  it('断言总数不超过基线（防回潮）', () => {
    const total = countAssertions()
    // 口径 = 排除 src/test/（测试里断言 mock 形状不算收敛对象）。执行本任务时先跑一次
    // countAssertions() 取实测值填入；本计划撰写时实测为 41。注意本仓常有并发会话在改前端，
    // 若执行时该值已变，以执行时实测为准（且不得放松到无意义的量级）。
    expect(total).toBeLessThanOrEqual(41)
  })

  it('收敛样例：stockApi.stats 的断言已消除', () => {
    const text = readFileSync(resolve(src, 'api/stock.ts'), 'utf-8')
    expect(text).not.toContain('as unknown as typeof resp.data')
  })
})

/**
 * 持久化缓存 buster 门禁的判定逻辑回归测试。
 *
 * 审计待核实 #20：buster 是 sessionStorage 里 vue-query 缓存的失效开关，
 * api.d.ts（后端契约生成物）改了 28 次而 buster 从未 bump → 老客户端可能带着
 * 与新 API 不匹配的持久化缓存运行。
 *
 * 锁三条：
 *   C1 hash 变了、buster 没变 → 门禁必须红；
 *   C2 hash 与 buster 都没变 → 绿（日常无契约变更时不打扰）；
 *   C3 --update 也拒绝「只换 hash 不 bump」，否则门禁可被顺手绕过。
 */
import { describe, it, expect } from 'vitest'
import {
  evaluate,
  evaluateUpdate,
  readBuster,
} from '../../scripts/check-query-cache-buster.mjs'

const SNAPSHOT = { buster: 'binfa-erp-v1', apiTypesSha256: 'aaa' }

describe('query-cache-buster 门禁', () => {
  it('从 main.ts 源码里取出 buster 字面量', () => {
    expect(readBuster("  buster: 'binfa-erp-v3',")).toBe('binfa-erp-v3')
    expect(readBuster('  buster: "binfa-erp-v4",')).toBe('binfa-erp-v4')
    expect(readBuster('  // 没有 buster')).toBeNull()
  })

  it('hash 变了但 buster 没 bump → 失败', () => {
    const result = evaluate({ currentBuster: 'binfa-erp-v1', currentHash: 'bbb', snapshot: SNAPSHOT })
    expect(result.ok).toBe(false)
    expect(result.errors.join()).toContain('buster 没 bump')
  })

  it('hash 与 buster 都没变 → 通过', () => {
    const result = evaluate({ currentBuster: 'binfa-erp-v1', currentHash: 'aaa', snapshot: SNAPSHOT })
    expect(result.ok).toBe(true)
    expect(result.errors).toEqual([])
  })

  it('bump 了但没 -update 快照 → 失败（提示同步快照）', () => {
    const result = evaluate({ currentBuster: 'binfa-erp-v2', currentHash: 'bbb', snapshot: SNAPSHOT })
    expect(result.ok).toBe(false)
    expect(result.errors.join()).toContain('与快照')
  })

  it('取不到 buster → 失败（防止改名后门禁空转）', () => {
    const result = evaluate({ currentBuster: null, currentHash: 'aaa', snapshot: SNAPSHOT })
    expect(result.ok).toBe(false)
    expect(result.errors.join()).toContain('找不到')
  })

  it('--update 拒绝只换 hash 不 bump', () => {
    const result = evaluateUpdate({ currentBuster: 'binfa-erp-v1', currentHash: 'bbb', snapshot: SNAPSHOT })
    expect(result.ok).toBe(false)
    expect(result.errors.join()).toContain('拒绝更新快照')
  })

  it('--update 允许「bump + 新 hash」一起更新', () => {
    const result = evaluateUpdate({ currentBuster: 'binfa-erp-v2', currentHash: 'bbb', snapshot: SNAPSHOT })
    expect(result.ok).toBe(true)
  })

  it('--update 允许仅 bump（hash 未变，手动清缓存）', () => {
    const result = evaluateUpdate({ currentBuster: 'binfa-erp-v2', currentHash: 'aaa', snapshot: SNAPSHOT })
    expect(result.ok).toBe(true)
  })
})

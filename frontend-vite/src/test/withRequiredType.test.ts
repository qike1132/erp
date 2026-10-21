/**
 * WithRequired 的编译期回归锁（审计 F1-1/F1-2 派生迁移的前提类型）。
 *
 * 为什么要有这条测试：`Omit<T, K> & Required<Pick<T, K>>` 少写一层 `Required<>` 也**不会报错**
 * ——`Pick<T, K>` 原样保留 `?` 修饰符，断言静默失效，代价转移到所有消费方
 * （2026-10-21 首次就是这么写的，vue-tsc 立刻报 `number | undefined` 不能赋给 `number`）。
 * 用 @ts-expect-error 把它钉死：断言一旦失效，下面那行就「没有错误可抑制」，
 * vue-tsc 以 TS2578 失败，`npm run type-check` 变红。
 */
import { describe, it, expect } from 'vitest'
import type { WithRequired } from '@/types'

type Base = { id: number; quantity?: number; note?: string }
type Fixed = WithRequired<Base, 'quantity'>

describe('WithRequired：只断言必填，不重写字段清单', () => {
  it('被断言的字段必须提供（缺它即编译错误），未断言字段仍保持可选', () => {
    const ok: Fixed = { id: 1, quantity: 2 }
    // @ts-expect-error quantity 已被断言为必填
    const missing: Fixed = { id: 1 }
    const partial: Fixed = { id: 1, quantity: 3 }

    expect(ok.quantity).toBe(2)
    expect(partial.note).toBeUndefined()
    // 仅为引用变量，真实断言由上一行的 @ts-expect-error 承担
    expect(missing.id).toBe(1)
  })
})

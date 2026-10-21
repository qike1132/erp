/**
 * WithItems 的编译期回归锁（审计 F1-1/F1-2 列表信封派生迁移的前提类型）。
 *
 * 这条测试钉的是「元素类型有没有被换回生成层的松散镜像」：
 * `Required<生成层信封>` 只去掉信封自身的 `?`，`items` 的元素仍是生成层元素（全可选），
 * 加强口径静默丢失，且**不会**在声明处报错——vue-tsc 只在消费方取值时才发现
 * `string | undefined` 不能赋给 `string`（2026-10-21 实测：改回 Required<> 后
 * CaseInventory/OutsourceShip 等一批视图立刻报 7 处）。
 * 用类型等价断言把它钉死：一旦退化，Equal<> 变成 false，赋值即 TS2322，`npm run type-check` 变红。
 */
import { describe, it, expect } from 'vitest'
import type { WithItems } from '@/types'

/** 模拟生成层信封：字段全可选，且引用的是生成层元素 */
type Loose = { id?: number; name?: string }
type GenEnvelope = { success?: boolean; items?: Array<Loose>; total?: number }
/** 模拟本地加强后的元素类型 */
type Strong = Required<Loose>

type Derived = WithItems<GenEnvelope, 'items', Strong>

/** 两个类型完全相同才为 true（TS 官方 ConditionalTypes 里的 Equal 惯用法） */
type Equal<X, Y> = (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? true : false

describe('WithItems：字段清单取生成层，元素类型锁定本地加强版', () => {
  it('items 的元素是加强后的类型，不是生成层的可选镜像', () => {
    const elementIsStrengthened: Equal<Derived['items'], Strong[]> = true
    // 退化成 Required<GenEnvelope> 时这一行会变成 false === true 的赋值错误
    expect(elementIsStrengthened).toBe(true)
  })

  it('未覆盖的字段仍由生成层供账并被断言为必填', () => {
    const ok: Derived = { success: true, items: [], total: 0 }
    // @ts-expect-error success 已被断言为必填
    const missing: Derived = { items: [], total: 0 }
    expect(ok.total).toBe(0)
    // 仅为引用变量，真实断言由上一行的 @ts-expect-error 承担
    expect(missing.items).toHaveLength(0)
  })
})

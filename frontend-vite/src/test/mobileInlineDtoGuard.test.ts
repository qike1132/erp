/**
 * 移动端禁止内联匿名 DTO + 共享订单类型不得丢字段（2026-10-17 审计 F1-3）。
 *
 * 缺陷：check:dto 只查**具名**声明（`interface X` / `type X`），匿名内联 DTO
 * （`ref<Array<{ id: number; order_no?: string; ... }>>`）完全绕过——而这正是
 * 10-14 `order_no` / `order_nos` 事故的前端面：移动端订单查询页自己抄了一份
 * 内联 DTO，字段与后端 OrderSerializer.LIST_CONFIG 一旦漂移就静默显示空值。
 *
 * 本测试锁两条不变量：
 * 1. src/mobile 下不得再用内联匿名对象类型标注响应式状态；
 * 2. 共享类型 OrderItem 必须带齐后端列表接口真实返回的 order_no / customer /
 *    product —— 否则「改成 API 签名推导」只是把内联 DTO 换成残缺类型，
 *    移动端依旧显示不出订单号与客户名（且不会有任何报错）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join, relative } from 'node:path'

const root = resolve(process.cwd())
const mobileDir = resolve(root, 'src', 'mobile')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else if (/\.(vue|ts)$/.test(entry)) out.push(full)
  }
  return out
}

/** 响应式状态上的内联匿名对象类型（ref/computed/shallowRef 的类型实参直接是 `{`） */
const INLINE_STATE_TYPE = /\b(?:ref|shallowRef|computed)\s*<\s*(?:Array\s*<\s*)?\{/g

describe('移动端内联匿名 DTO 禁令（F1-3）', () => {
  it('src/mobile 下没有用内联匿名对象类型标注响应式状态', () => {
    const violations: string[] = []
    for (const file of walk(mobileDir)) {
      const src = readFileSync(file, 'utf-8')
      src.split(/\r?\n/).forEach((line, i) => {
        INLINE_STATE_TYPE.lastIndex = 0
        if (INLINE_STATE_TYPE.test(line)) {
          violations.push(`${relative(root, file).replaceAll('\\', '/')}:${i + 1}`)
        }
      })
    }
    expect(
      violations,
      `移动端出现内联匿名 DTO（应改为 API 签名推导）：\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('订单查询页与来料登记页都改用 API 签名推导（不再自抄一份字段表）', () => {
    const customerOrder = readFileSync(
      resolve(root, 'src', 'mobile', 'views', 'customer-order', 'MCustomerOrderView.vue'),
      'utf-8',
    )
    const incoming = readFileSync(
      resolve(root, 'src', 'mobile', 'views', 'incoming', 'MIncomingView.vue'),
      'utf-8',
    )
    expect(customerOrder).toContain("Awaited<ReturnType<typeof orderApi.list>>")
    expect(incoming).toContain("Awaited<ReturnType<typeof materialApi.overview>>")
    expect(incoming).toContain("Awaited<ReturnType<typeof materialApi.registrations>>")
  })
})

describe('共享订单类型不得丢字段（F1-3 的根因侧）', () => {
  it('OrderItem 声明了后端列表接口真实返回的 order_no / customer / product', () => {
    const typesSrc = readFileSync(resolve(root, 'src', 'types', 'index.ts'), 'utf-8')
    const block = /export interface OrderItem \{([\s\S]*?)\n\}/.exec(typesSrc)
    expect(block, '未找到 OrderItem 接口声明').not.toBeNull()
    const body = block?.[1] ?? ''
    expect(body).toMatch(/\border_no\??:/)
    expect(body).toMatch(/\bcustomer\??:/)
    expect(body).toMatch(/\bproduct\??:/)
  })
})

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * 回归锁（2026-11-16 上线前审计 H-5）：退货管理页列表查询的门控必须与后端**同源**。
 *
 * 事故形态：`stock_return_manage`（「退货管理(全部)」）是 seed_nav 里的**顶层码**，
 * 与 `stock_return_view` 并列两个勾选框。后端 `User.has_permission` 对 `*_manage`
 * 会自动放行同名 `*_view`，导航侧 `nav_context` 也把两个码一起展开 —— 唯独前端列表
 * 查询用了严格 `hasPermission('stock_return_view')`，于是只授 manage 的账号：
 * 侧栏有入口、`canManage=true` 能建单，**列表却永远显示「暂无退货记录」**（query 被禁用）。
 *
 * 为什么用源码断言而不是挂载组件：这个 bug 的形状是「一行门控写错」，而挂载
 * StockReturnView 需要 6 个 PrimeVue 重组件 + auth store + vue-query 全量桩，
 * 成本远高于收益。这里把判定收敛到**唯一那一行**（`enabled:` 表达式）。
 *
 * ── 2026-11-17 OCR 复审：本文件从「字符串包含」改为「结构化断言」 ──
 * 旧写法用正则 `enabled:\s*computed\(\(\)\s*=>[^\n]*`（此处省略两端斜杠）抓整行，
 * 其中 `[^\n]*` **包含行尾注释**，再用 `toContain('stock_return_manage')` /
 * `!expr.includes('stock_return_manage')` 判定。
 * 于是补一句注释就能双绿绕过这把锁：
 *
 *     enabled: computed(() => auth.hasPermission('stock_return_view')), // stock_return_manage 由后端放行
 *
 *   - 用例「必须同时含两个码」：命中的是注释里的 `stock_return_manage`；
 *   - 用例「不能退化成单码」：`!expr.includes('stock_return_manage')` 因注释变成 false。
 * 现在改为：**先剥离注释**（`//...` 与块注释），再断言 `hasAnyPermission([...])` 的
 * **调用形态**（数组实参里恰好是 view + manage 两个码，顺序/排版无关），并保留
 * 单码 `hasPermission('...')` 的反例样本（含上面那条带行尾注释的逃生口样本）。
 */
const SOURCE = readFileSync(
  join(process.cwd(), 'src/views/stock-return/composables/useStockReturn.ts'),
  'utf8',
)

const VIEW_CODE = 'stock_return_view'
const MANAGE_CODE = 'stock_return_manage'

/**
 * 剥离注释（OCR 复审 2026-11-17 的兜底）：判定任何表达式之前先剔掉 `//` 行注释与块注释，
 * 保证「注释里写个码」不再能影响断言结果。
 */
function stripComments(code: string): string {
  return code.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')
}

/**
 * 抽出列表 query 的 `enabled:` 表达式。用括号配平扫描而不是 `[^\n]*`：
 * 门控若被格式化成多行，`[^\n]*` 会截断成半句、造成假红。
 */
function enabledExpression(): string {
  const head = /enabled:\s*computed\s*\(/.exec(SOURCE)
  expect(head, 'useStockReturn.ts 里找不到列表 query 的 enabled 门控').not.toBeNull()
  const start = (head as RegExpExecArray).index
  let depth = 0
  for (let i = start + (head as RegExpExecArray)[0].length - 1; i < SOURCE.length; i += 1) {
    const ch = SOURCE[i]
    if (ch === '(') depth += 1
    else if (ch === ')') {
      depth -= 1
      if (depth === 0) return SOURCE.slice(start, i + 1)
    }
  }
  throw new Error('useStockReturn.ts 的 enabled: computed(...) 括号不配平')
}

/** 调用形态：`hasAnyPermission([ ... ])`，`\s*` 同时允许换行，单双引号都认。 */
const ANY_OF_CALL = /hasAnyPermission\s*\(\s*\[([\s\S]*?)\]\s*\)/

/** 门控里不允许出现的严格单码调用。注意 `hasAnyPermission` 不含子串 `hasPermission`，不会自匹配。 */
const STRICT_SINGLE_CALL = /\bhasPermission\s*\(/

/** 解析 `[...]` 实参里的权限码。 */
function codesOf(arrayBody: string): string[] {
  return Array.from(arrayBody.matchAll(/['"]([A-Za-z0-9_]+)['"]/g), (m) => m[1])
}

/**
 * 结构化判定（本文件的唯一真源）：不做任何字符串包含。
 * 为 true 当且仅当剥离注释后——
 *  1. 有 `hasAnyPermission([...])` 调用；
 *  2. 数组里的码**恰好**是 {view, manage}（顺序无关，多一个少一个都算错）；
 *  3. 表达式里没有 `hasPermission('单码')` 这种严格单码判断。
 * 被测的真实表达式与下面的反例样本走的是**同一个**判定函数，
 * 所以「反例必须为 false」真的能证伪这条锁，而不是各说各话。
 */
function isDualCodeGate(expression: string): boolean {
  const code = stripComments(expression)
  const call = ANY_OF_CALL.exec(code)
  if (call === null) return false
  const actual = codesOf(call[1]).sort()
  const expected = [VIEW_CODE, MANAGE_CODE].sort()
  const sameSet = actual.length === expected.length && actual.every((c, i) => c === expected[i])
  return sameSet && !STRICT_SINGLE_CALL.test(code)
}

describe('退货列表门控与后端同源（H-5）', () => {
  it('enabled 是 hasAnyPermission([view, manage]) 的调用形态（不是字符串包含）', () => {
    const code = stripComments(enabledExpression())
    expect(code).toMatch(ANY_OF_CALL)
    // 锁住实现当前的真实排版（单行、view 在前）。若有人调换数组顺序，语义不变但请同步这行。
    expect(code).toMatch(
      /hasAnyPermission\s*\(\s*\[\s*['"]stock_return_view['"]\s*,\s*['"]stock_return_manage['"]\s*\]\s*\)/,
    )
  })

  it('enabled 的权限码集合恰好是 {stock_return_view, stock_return_manage}', () => {
    const expr = enabledExpression()
    const call = ANY_OF_CALL.exec(stripComments(expr))
    expect(call, `enabled 里没有 hasAnyPermission([...]) 调用：${expr}`).not.toBeNull()
    expect(codesOf((call as RegExpExecArray)[1]).sort()).toEqual([MANAGE_CODE, VIEW_CODE].sort())
    expect(isDualCodeGate(expr), `enabled 门控不是双码容错形态：${expr}`).toBe(true)
  })

  it('enabled 不能再退化成「只认 view」的单码严格判断', () => {
    const expr = enabledExpression()
    const code = stripComments(expr)
    expect(STRICT_SINGLE_CALL.test(code), `enabled 里出现了严格单码 hasPermission(：${expr}`).toBe(false)
    expect(isDualCodeGate(expr), `enabled 门控退化成单码：${expr}`).toBe(true)
  })

  it('反例：单码 / 注释逃生口都必须判定为不合格', () => {
    const rejected = [
      /** 事故原始形态 */
      "enabled: computed(() => auth.hasPermission('stock_return_view'))",
      /** OCR 复审 2026-11-17 复现的逃生口：单码 + 行尾注释（旧断言在此双绿） */
      "enabled: computed(() => auth.hasPermission('stock_return_view')), // stock_return_manage 由后端放行",
      /** 只认 manage 同样不合规（门控必须两者都认） */
      "enabled: computed(() => auth.hasPermission('stock_return_manage'))",
      /** 换成 hasAnyPermission 但只给一个码，仍是单码退化 */
      "enabled: computed(() => auth.hasAnyPermission(['stock_return_view']))",
      "enabled: computed(() => auth.hasAnyPermission(['stock_return_manage']))",
      /** 双码齐全，但外面又套了一层严格单码判断（等于回到单码语义） */
      "enabled: computed(() => auth.hasAnyPermission(['stock_return_view', 'stock_return_manage']) && auth.hasPermission('stock_return_view'))",
    ]
    for (const sample of rejected) {
      expect(isDualCodeGate(sample), `这条门控必须被判不合格：${sample}`).toBe(false)
    }
  })

  it('反例：旧断言的漏洞来源——行尾注释能骗过 includes/toContain', () => {
    const escapeHatch =
      "enabled: computed(() => auth.hasPermission('stock_return_view')), // stock_return_manage 由后端放行"
    // 旧写法（字符串包含）在这里确实是绿的：这就是本次改造的动机。
    expect(escapeHatch).toContain(MANAGE_CODE)
    expect(escapeHatch.includes(MANAGE_CODE)).toBe(true)
    // 剥离注释后注释里的码消失 → 结构化判定判红。
    expect(stripComments(escapeHatch)).not.toContain(MANAGE_CODE)
    expect(isDualCodeGate(escapeHatch)).toBe(false)
  })

  it('剥离注释是幂等的：真实门控补一句行尾注释后判定不变', () => {
    const expr = enabledExpression()
    expect(isDualCodeGate(`${expr} // ${MANAGE_CODE} 由后端放行`)).toBe(true)
    expect(isDualCodeGate(`${expr} /* ${MANAGE_CODE} 由后端放行 */`)).toBe(true)
  })
})

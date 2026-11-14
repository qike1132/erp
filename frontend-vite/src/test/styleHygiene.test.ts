/**
 * 样式卫生棘轮：行内 style 只降不升。
 *
 * 为什么不直接清零：2026-11-14 审核逐类核查后确认，存量的 223 处里绝大多数是
 * 合理用法，硬替换会引入真实回归 ——
 *   · `style="width: 100%"`（23 处）几乎都用在 UiSelect/UiDatePicker 上：这些组件
 *     默认宽度不是 100%，换 `class="w-full"` 会因特异性(0,1,0)低于组件 scoped 样式
 *     ([data-v-x] 0,2,0) 而失效，布局回退。
 *   · 固定像素宽度（约 78 处）是表格列宽/输入框宽度，属上下文相关布局值。
 *   · `style="display: none"`（4 处）全是隐藏的 `<input type="file">`，靠 label 触发。
 *
 * 所以这里锁「不再增长」：新增行内样式会让总数越线变红，存量随改动自然下降。
 * 装饰类（颜色/字号/圆角/阴影）没有上述正当理由，基线单独收紧。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/** 静态行内样式基线（2026-11-14 实测）。只降不升。 */
const BASELINE_TOTAL = 223
/** 其中装饰类基线：这类应走 class 或设计令牌，不该出现在行内。 */
const BASELINE_DECO = 57

const DECO_RE =
  /(?:^|;)\s*(?:color|background|background-color|border|border-color|border-radius|font-size|box-shadow)\s*:/

function collectVueFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) collectVueFiles(full, out)
    else if (name.endsWith('.vue')) out.push(full)
  }
  return out
}

interface InlineStyle {
  file: string
  line: number
  decl: string
}

/** 静态行内 style（排除 `:style` 动态绑定：它承载的是计算值，本就无法用 class 表达） */
function collectInlineStyles(): InlineStyle[] {
  const rows: InlineStyle[] = []
  for (const file of collectVueFiles('src')) {
    const rel = file.replace(/\\/g, '/')
    if (rel.startsWith('src/test/')) continue
    const lines = readFileSync(file, 'utf8').split(/\r?\n/)
    lines.forEach((text, idx) => {
      for (const m of text.matchAll(/(?<!:)style="([^"]*)"/g)) {
        rows.push({ file: rel, line: idx + 1, decl: (m[1] ?? '').trim() })
      }
    })
  }
  return rows
}

function report(rows: InlineStyle[]): string {
  return rows.map((r) => `${r.file}:${r.line}  ${r.decl.slice(0, 60)}`).join('\n')
}

describe('样式卫生棘轮（行内 style 只降不升）', () => {
  const all = collectInlineStyles()
  const deco = all.filter((r) => DECO_RE.test(r.decl))

  it(`静态行内 style 总数不得超过基线 ${BASELINE_TOTAL}`, () => {
    expect(all.length, `当前 ${all.length} 处，新增请改用 class。全量位置：\n${report(all)}`).toBeLessThanOrEqual(
      BASELINE_TOTAL,
    )
  })

  it(`行内装饰样式不得超过基线 ${BASELINE_DECO}（颜色/字号/圆角/阴影应走 class 或令牌）`, () => {
    expect(deco.length, `当前 ${deco.length} 处：\n${report(deco)}`).toBeLessThanOrEqual(BASELINE_DECO)
  })

  it('基线不得虚高：总数明显低于基线时应同步下调', () => {
    // 防止「删了 50 处但基线不动」→ 后续又长回来。留 10 处容差给正常波动。
    expect(all.length, `当前 ${all.length}，基线 ${BASELINE_TOTAL}，请下调 BASELINE_TOTAL`).toBeGreaterThan(
      BASELINE_TOTAL - 10,
    )
  })
})

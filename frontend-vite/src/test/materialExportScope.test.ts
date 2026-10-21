/** P1-25：来料进度/历史两个导出按钮必须传不同 scope。 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// vitest 的 root 是 frontend-vite，直接按仓内相对路径读取
const source = readFileSync('src/views/material/MaterialView.vue', 'utf-8')

/** 取出某个具名函数的函数体（按大括号配平截取） */
function bodyOf(fnName: string): string {
  const start = source.indexOf(`function ${fnName}(`)
  if (start < 0) throw new Error(`未找到函数 ${fnName}`)
  const open = source.indexOf('{', start)
  let depth = 0
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(open, i + 1)
    }
  }
  throw new Error(`函数 ${fnName} 的函数体未闭合`)
}

describe('来料导出 tab 口径', () => {
  // 按**每个处理器**分别断言：只断言「文件里同时出现过 progress 和 history」
  // 会在两个 handler 的 scope 被对调时假绿（两处都还出现这两个词）。
  it('exportData 只导进度', () => {
    const body = bodyOf('exportData')
    expect(body).toMatch(/scope:\s*'progress'/)
    expect(body).not.toMatch(/scope:\s*'history'/)
  })

  it('exportHistory 只导历史', () => {
    const body = bodyOf('exportHistory')
    expect(body).toMatch(/scope:\s*'history'/)
    expect(body).not.toMatch(/scope:\s*'progress'/)
  })
})

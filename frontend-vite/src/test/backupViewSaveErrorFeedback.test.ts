import { describe, expect, it } from 'vitest'
// 源码级断言：用 Vite 的 ?raw 读原文，避免依赖 node:fs 类型
import backupViewSource from '@/views/backup/BackupView.vue?raw'

/**
 * /backup 审计（high）：保存定时任务 / 保存备份路径**吞掉后端报错**。
 *
 * 原来两处都是 `try { await ... } finally { ... }` —— 没有 catch。
 * 后端返回 400（cron 非法、路径不可写等）时异常无人接，变成未处理的 promise
 * rejection：界面既不提示也不回滚，运维只看到"点了没反应"，无从修正输入。
 *
 * 这里锁"必须把失败告诉用户"这一行为，而不是断言某种具体写法：
 * 只要函数体内不存在 catch，或者没有触发用户可见提示，即判失败。
 */

/**
 * 取出 `async function <name>(...) { ... }` 的完整函数体。
 *
 * 必须先配平**参数列表的圆括号**再找花括号：参数带对象类型注解
 * （`data: { name: string }`）时，第一个 `{` 属于类型注解而非函数体。
 */
function functionBody(source: string, name: string): string {
  const start = source.indexOf(`async function ${name}(`)
  if (start < 0) throw new Error(`找不到 async function ${name}`)

  const parenOpen = source.indexOf('(', start)
  let parens = 0
  let parenClose = -1
  for (let i = parenOpen; i < source.length; i += 1) {
    if (source[i] === '(') parens += 1
    else if (source[i] === ')') {
      parens -= 1
      if (parens === 0) {
        parenClose = i
        break
      }
    }
  }
  if (parenClose < 0) throw new Error(`${name} 参数列表不配平`)

  const open = source.indexOf('{', parenClose)
  let depth = 0
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    else if (source[i] === '}') {
      depth -= 1
      if (depth === 0) return source.slice(open, i + 1)
    }
  }
  throw new Error(`${name} 花括号不配平`)
}

describe('BackupView 保存类操作必须反馈失败', () => {
  for (const fn of ['saveSchedule', 'savePath', 'deleteSchedule']) {
    it(`${fn} 捕获异常并提示用户`, () => {
      const body = functionBody(backupViewSource, fn)

      expect(body, `${fn} 没有 catch —— 后端 400 会被静默吞掉`).toMatch(/\bcatch\b/)
      expect(body, `${fn} 捕获了却没告诉用户`).toMatch(/toast\.(error|warning)/)
    })
  }
})

import { describe, expect, it } from 'vitest'
// 源码级断言：用 Vite 的 ?raw 读原文，避免依赖 node:fs 类型
import backupViewSource from '@/views/backup/BackupView.vue?raw'

/**
 * /backup 审计：4 处**读取**失败被静默吞掉。
 *
 * loadStatus / loadSchedules / loadSettings / loadRecords 原来都是
 * `try { ... } catch { xxx.value = null/[] } finally { ... }`
 * —— 只有 catch、把值置空，**没有任何用户可见提示**。
 *
 * 后果比写操作更危险：本页是运维确认「备份到底还正常吗」的地方。
 *   - BackupOverviewCards.vue 用 `props.status ?? {}` 兜底，status=null 时渲染
 *     「上次备份：暂无 / 备份总数：0 个 / 健康度：—」；
 *   - BackupRecordTable 渲染「暂无备份记录」；ScheduleConfig 渲染「暂无定时任务」。
 * 这些空态与「从没配过备份」视觉完全一致。后端进程挂掉、网络断、500 时，
 * 管理员打开这页看到全空，最可能得出的结论是"没备份"，而那正是最坏的场景。
 *
 * request.ts 的响应拦截器只对 401（刷新重放）/403（toast.warning）做事，
 * 5xx 与网络错误一律 reject 抛回调用方 —— 而调用方正是这个静默 catch。
 * main.ts 的 errorHandler 只管渲染错误、unhandledrejection 只 console.error，
 * 都到不了已被组件 catch 的分支。所以全局没有兜底，必须由组件自己提示。
 *
 * 这里锁「读取失败必须告诉用户」这一行为，不锁定具体文案。
 */

/**
 * 取出 `async function <name>(...) { ... }` 的完整函数体。
 *
 * 必须先配平**参数列表的圆括号**再找花括号：参数带对象类型注解
 * （`data: { name: string }`）时，第一个 `{` 属于类型注解而非函数体。
 * 与 backupViewSaveErrorFeedback.test.ts 同一套实现（刻意不复用，两文件各自独立可读）。
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

describe('BackupView 读取失败必须告知用户', () => {
  for (const fn of ['loadStatus', 'loadSchedules', 'loadSettings', 'loadRecords']) {
    it(`${fn} 捕获异常并提示用户`, () => {
      const body = functionBody(backupViewSource, fn)

      expect(body, `${fn} 没有 catch —— 后端 5xx/网络错误会变成未处理的 rejection`).toMatch(/\bcatch\b/)
      expect(body, `${fn} 捕获了却没告诉用户 —— 空列表会被读成"没有备份"`).toMatch(
        /toast\.(error|warning)/,
      )
    })
  }
})

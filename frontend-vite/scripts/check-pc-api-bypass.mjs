#!/usr/bin/env node
/**
 * PC 端 API 层绕过检查（补 check-api-alignment.mjs 的盲区）。
 *
 * 背景（2026-09-18）：`check-api-alignment.mjs` 只校验 `src/mobile/`，
 * PC 端 `src/views/` 完全不在扫描范围内，于是 9 处「视图层自拼端点」的调用
 * 长期无人拦截，并已产生两个稳定失败的真实缺陷：
 *
 *   - `POST /batch/import-products` —— 后端**不存在**该路由（真名是 batch-import）；
 *   - `POST /ocr-import/upload`   —— API 层签名收下 session_id 却没拼进 URL，
 *      后端 Query(..., 必填) 必然 422。
 *
 * 两类缺陷的共同根因是「端点路径散落在视图层」，故本检查锁死：
 *   1) views 下不得从 `@/api/request` 以任何形式取得请求函数
 *      （具名 / `* as` / default / 动态 import / 相对路径一律覆盖）；
 *   2) views 下不得出现 `/api/v1/...` 端点（含同文件内跨行拼接、模板串拼接）。
 *
 * ⚠️ 已知边界（有意不查，避免误报）：
 *   - **运行时拼接**无法静态拦截（如从配置/变量拼出路径）。本检查是"提高绕过成本"
 *     的第一道闸，不是证明级工具；真正的保证来自 code review。
 *   - 只扫 `src/views/`；`src/api/` 自身是封装层，允许出现端点字面量。
 *
 * 用法: node scripts/check-pc-api-bypass.mjs
 * 退出码: 0 = 无绕过, 1 = 发现绕过
 */
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const srcDir = resolve(__dirname, '..', 'src')

/** 传输层中「非请求」的导出：views 允许导入这些 */
const ALLOWED_TRANSPORT_EXPORTS = new Set(['resolveStaticUrl', 'clearCsrfCache'])
/** 请求函数名（含 default axios 实例 `service`） */
const REQUEST_FNS = new Set(['get', 'post', 'put', 'del', 'patch', 'upload', 'download', 'postDownload', 'service'])

function walk(dir, exts) {
  const out = []
  let entries
  try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return out }
  for (const e of entries) {
    const p = join(dir, e.name)
    if (e.isDirectory()) {
      if (e.name === 'node_modules' || e.name === 'dist') continue
      out.push(...walk(p, exts))
    } else if (e.isFile() && exts.some((x) => e.name.endsWith(x))) {
      out.push(p)
    }
  }
  return out
}

/** 去掉行注释，避免注释里出现端点示例造成误报（不处理块注释内的字符串） */
function stripLineComment(line) {
  let inStr = null
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (inStr) {
      if (ch === "\\") i += 1
      else if (ch === inStr) inStr = null
    } else if (ch === "'" || ch === '"' || ch === '`') {
      inStr = ch
    } else if (ch === '/' && line[i + 1] === '/') {
      return line.slice(0, i)
    }
  }
  return line
}

/** 从 import 子句 `{ a, b as c }` 取出原始导出名 */
function parseNamedImports(clause) {
  return clause.split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => s.replace(/^type\s+/, '').split(/\s+as\s+/)[0].trim())
    .filter(Boolean)
}

const violations = []
const files = walk(join(srcDir, 'views'), ['.vue', '.ts'])

for (const file of files) {
  let raw
  try { raw = readFileSync(file, 'utf-8') } catch { continue }
  const rel = relative(srcDir, file)
  const code = raw
    .split(/\r?\n/)
    .map((l, i) => [i + 1, stripLineComment(l)])
    .filter(([, l]) => l.trim())

  // 规则 1：任何形式从传输层取得请求函数
  //   覆盖 import { get } / import * as r / import r from / import("...")
  const importRe = /import\s+(?:type\s+)?(?:\*\s+as\s+([\w$]+)|([\w$]+)|\{([^}]*)\})\s*from\s*['"]([^'"]+)['"]/g
  const importText = code.map(([, l]) => l).join('\n')
  let m
  while ((m = importRe.exec(importText)) !== null) {
    const spec = m[4].replace(/\\/g, '/')
    // 命中传输层：@/api/request 与相对路径 ./request、../api/request
    if (!/(^|\/)api\/request$/.test(spec)) continue
    const nsName = m[1]
    const defaultName = m[2]
    const named = m[3]
    if (nsName) {
      violations.push({ rel, detail: `以命名空间导入传输层: import * as ${nsName} from '${m[4]}'` })
    } else if (defaultName) {
      // default 即 axios 实例（request.ts:37），可用 .post/.get/...
      violations.push({ rel, detail: `以 default 导入传输层: import ${defaultName} from '${m[4]}'` })
    } else if (named) {
      const names = parseNamedImports(named)
      const offenders = names.filter((n) => REQUEST_FNS.has(n) && !ALLOWED_TRANSPORT_EXPORTS.has(n))
      if (offenders.length) {
        violations.push({ rel, detail: `直接导入请求函数: ${offenders.join(', ')}` })
      }
    }
  }
  // 动态 import
  const dynRe = /import\s*\(\s*['"]([^'"]+)['"]\s*\)/g
  while ((m = dynRe.exec(importText)) !== null) {
    const spec = m[1].replace(/\\/g, '/')
    if (/(^|\/)api\/request$/.test(spec)) {
      violations.push({ rel, detail: `动态导入传输层: import('${m[1]}')` })
    }
  }

  // 规则 2：端点字面量。逐行查完整字面量；再在整文件（去注释）里查跨行拼接。
  const lineRe = /['"`](\/api\/v1\/[^'"`]*)['"`]/
  for (const [n, line] of code) {
    const hit = line.match(lineRe)
    if (hit && !hit[1].includes('${')) {
      violations.push({ rel, line: n, detail: `硬编码端点: ${hit[1]}` })
    }
  }
  // 跨行/拼接：把代码压成一串后匹配 /api/v1/ 且其后紧邻引号拼接（例如 "/api" + "/v1/x"）
  const joined = code.map(([, l]) => l).join(' ¶ ')
  const concatRe = /['"`]\/api(?:\/v1)?['"`]\s*\+\s*['"`][^'"`]*v1/g
  if (concatRe.test(joined)) {
    violations.push({ rel, detail: '端点被拆分拼接（如 "/api" + "/v1/..."）' })
  }
}

console.log('=== PC 端 API 层绕过检查 ===')
console.log(`扫描文件数: ${files.length}（src/views 下 .vue/.ts）`)

if (violations.length > 0) {
  console.warn(`\n⚠ 发现 ${violations.length} 处绕过 API 层的调用:`)
  for (const v of violations) {
    console.warn(`  ${v.rel}${v.line ? ':' + v.line : ''}  ${v.detail}`)
  }
  console.warn('\n建议: 在 src/api/ 对应模块补充端点定义，再从视图层调用该函数。')
  process.exit(1)
}

console.log('\n✓ PC 端所有端点调用均经 src/api/ 层')
process.exit(0)

#!/usr/bin/env node
/**
 * CI 路由一致性检查（真校验）
 *
 * 数据源：src/router/index.ts 的 pcRoutes / mobileRoutes 两个 RouteRecordRaw 数组。
 *
 * 判定规则：
 *   1) 端独有路由（只在一端出现的路径）属正常差异，只打印、不阻断；
 *   2) 共有功能路由按命名约定配对：移动端路由名 = 'M' + PC 端路由名
 *      （例如 MDashboard 与 Dashboard）。配对双方的 path 字面量必须完全一致，
 *      否则打印不一致明细并以退出码 1 结束；
 *   3) 无法按命名配对的移动端路由（设备独有页，如 MProfile）只打印、不阻断。
 *
 * 旧实现的问题：用「共有集合」与「共有集合」求差（sharedPc 与 sharedMobile 恒等），
 * mismatched 永远为空，exit(1) 分支不可达 —— 本门禁永远绿灯，等于不存在。
 * 本版改为按命名配对比较路径字面量，恢复真实失败能力。
 *
 * 用法：node scripts/check-route-alignment.mjs [--router <index.ts>] [--json] [--verbose]
 * 退出码：0 = 一致, 1 = 共有功能路径不一致, 2 = 环境异常（路由文件读不到 / 解析不出数组）
 *
 * 注意：本脚本的 stdout 会被 scripts/prod_audit/layers/l5_api_contract.py 逐行匹配
 *   (diff|mismatch|missing|fail|error|✗) 生成审计问题，因此正常输出里不要出现这些词，
 *   只有真正的失败行才以 '✗' 开头。
 */
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const BACKTICK = String.fromCharCode(96)
const QUOTE_CHARS = new Set(["'", '"', BACKTICK])

function printUsage() {
  console.log('用法: node scripts/check-route-alignment.mjs [--router <index.ts>] [--json] [--verbose]')
}

function parseArgs(argv) {
  const opts = { router: null, json: false, verbose: false }
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--json') opts.json = true
    else if (arg === '--verbose' || arg === '-v') opts.verbose = true
    else if (arg === '--router') opts.router = argv[++i] ?? null
    else if (arg.startsWith('--router=')) opts.router = arg.slice('--router='.length)
    else if (arg === '--help' || arg === '-h') { printUsage(); process.exit(0) }
    else { console.error('未知参数: ' + arg); printUsage(); process.exit(2) }
  }
  return opts
}

/** 从 text[i] 起读一个字符串字面量（单引号 / 双引号 / 反引号）。 */
function readStringAt(text, i) {
  const quote = text[i]
  if (!QUOTE_CHARS.has(quote)) return null
  let j = i + 1
  let value = ''
  while (j < text.length) {
    const ch = text[j]
    if (ch.charCodeAt(0) === 92) { value += text[j + 1] ?? ''; j += 2; continue }
    if (ch === quote) return { value, end: j }
    value += ch
    j++
  }
  return null
}

/** 取出 "const <name> = [ ... ]" 里数组体的文本（方括号已剥掉）。 */
function findArrayContent(content, arrayName) {
  const startIdx = content.indexOf('const ' + arrayName)
  if (startIdx === -1) return null
  const eqBracketIdx = content.indexOf('= [', startIdx)
  if (eqBracketIdx === -1) return null
  const bracketStart = eqBracketIdx + 2
  let depth = 1
  for (let i = bracketStart + 1; i < content.length; i++) {
    if (content[i] === '[') depth++
    else if (content[i] === ']') {
      depth--
      if (depth === 0) return content.slice(bracketStart + 1, i)
    }
  }
  return null
}

/** 收集 text 里最外层的对象字面量文本。 */
function collectObjects(text) {
  const out = []
  let depth = 0
  let start = -1
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (ch === '{') {
      if (depth === 0) start = i
      depth++
    } else if (ch === '}') {
      if (depth > 0) depth--
      if (depth === 0 && start !== -1) { out.push(text.slice(start, i + 1)); start = -1 }
    }
  }
  return out
}

/** 递归收集任意嵌套深度的对象字面量（父对象与其 children 里的子对象都算）。 */
function collectObjectsDeep(text, acc) {
  const bag = acc ?? []
  for (const obj of collectObjects(text)) {
    bag.push(obj)
    collectObjectsDeep(obj.slice(1, -1), bag)
  }
  return bag
}

/** 只取对象自身那一层（截到第一个内层花括号），避免把 children 的 path/name 读进来。 */
function headOf(objText) {
  const inner = objText.slice(1, -1)
  const braceIdx = inner.indexOf('{')
  return braceIdx === -1 ? inner : inner.slice(0, braceIdx)
}

function pickLiteral(head, key) {
  const idx = head.indexOf(key + ':')
  if (idx === -1) return null
  let i = idx + key.length + 1
  while (i < head.length && head[i].trim() === '') i++
  const parsed = readStringAt(head, i)
  return parsed === null ? null : parsed.value
}

/** 抽出一个路由数组里的所有 { path, name }（父子路由都算）。 */
function extractRoutes(content, arrayName) {
  const arrayContent = findArrayContent(content, arrayName)
  if (arrayContent === null) return null
  const routes = []
  for (const obj of collectObjectsDeep(arrayContent)) {
    const head = headOf(obj)
    const path = pickLiteral(head, 'path')
    const name = pickLiteral(head, 'name')
    if (path === null && name === null) continue
    routes.push({ path, name })
  }
  return routes
}

/** 可比较的路径：非空、且不是带参数的模板路径。 */
function isComparablePath(p) {
  return typeof p === 'string' && p !== '' && !p.includes(':')
}

function main() {
  const opts = parseArgs(process.argv.slice(2))
  const routerFile = opts.router
    ? resolve(process.cwd(), opts.router)
    : resolve(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'router', 'index.ts')

  let content
  try {
    content = readFileSync(routerFile, 'utf-8')
  } catch (err) {
    console.error('[ERROR] 读取路由文件失败: ' + routerFile + ' (' + (err && err.code ? err.code : err) + ')')
    process.exit(2)
  }

  const pcRoutes = extractRoutes(content, 'pcRoutes')
  const mobileRoutes = extractRoutes(content, 'mobileRoutes')
  if (pcRoutes === null || mobileRoutes === null) {
    console.error('[ERROR] 无法从 ' + routerFile + ' 解析出 pcRoutes / mobileRoutes 数组')
    process.exit(2)
  }

  const pcPaths = new Set(pcRoutes.map((r) => r.path).filter(isComparablePath))
  const mobilePaths = new Set(mobileRoutes.map((r) => r.path).filter(isComparablePath))
  const pcByName = new Map(pcRoutes.filter((r) => r.name).map((r) => [r.name, r.path]))
  const mobileByName = new Map(mobileRoutes.filter((r) => r.name).map((r) => [r.name, r.path]))

  const pairs = []
  const unpairedMobile = []
  for (const [mobileName, mobilePath] of mobileByName) {
    const pcName = mobileName.startsWith('M') ? mobileName.slice(1) : ''
    if (pcName && pcByName.has(pcName)) {
      const pcPath = pcByName.get(pcName)
      pairs.push({ pcName, mobileName, pcPath, mobilePath, consistent: pcPath === mobilePath })
    } else {
      unpairedMobile.push({
        name: mobileName,
        path: mobilePath,
        pathSharedWithPc: isComparablePath(mobilePath) && pcPaths.has(mobilePath),
      })
    }
  }
  pairs.sort((a, b) => a.pcName.localeCompare(b.pcName))

  const mismatches = pairs.filter((p) => !p.consistent)
  const pcOnlyPaths = [...pcPaths].filter((p) => !mobilePaths.has(p)).sort()
  const mobileOnlyPaths = [...mobilePaths].filter((p) => !pcPaths.has(p)).sort()
  const sharedPaths = [...pcPaths].filter((p) => mobilePaths.has(p)).sort()

  const report = {
    status: mismatches.length === 0 ? 'consistent' : 'inconsistent',
    routerFile,
    stats: {
      pcPaths: pcPaths.size,
      mobilePaths: mobilePaths.size,
      sharedPaths: sharedPaths.length,
      sharedFeatures: pairs.length,
      unpairedMobileRoutes: unpairedMobile.length,
    },
    pairs,
    mismatches: mismatches.map((p) => ({ pcName: p.pcName, mobileName: p.mobileName, pcPath: p.pcPath, mobilePath: p.mobilePath })),
    pcOnlyPaths,
    mobileOnlyPaths,
    unpairedMobileRoutes: unpairedMobile,
  }

  if (opts.json) {
    console.log(JSON.stringify(report, null, 2))
    process.exit(mismatches.length === 0 ? 0 : 1)
  }

  console.log('=== 路由一致性检查 ===')
  console.log('PC 端路由数: ' + pcPaths.size)
  console.log('移动端路由数: ' + mobilePaths.size)
  console.log('共有路径数: ' + sharedPaths.length)
  console.log('共享功能配对: ' + pairs.length + ' 项（移动端 name = M + PC 端 name）')

  if (opts.verbose) {
    for (const p of pairs) console.log('  ' + p.mobileName + ' <-> ' + p.pcName + '  (' + p.pcPath + ')')
  }

  if (unpairedMobile.length > 0) {
    console.log('\n未配对移动端路由 (' + unpairedMobile.length + '):')
    for (const u of unpairedMobile) {
      console.log('  - ' + u.name + (u.path === null ? '' : '  [' + u.path + ']') + (u.pathSharedWithPc ? '  (路径与 PC 端共有)' : ''))
    }
  }
  if (pcOnlyPaths.length > 0) {
    console.log('\n⚠ PC 端独有路由 (' + pcOnlyPaths.length + '):')
    pcOnlyPaths.forEach((p) => console.log('  - /' + p))
  }
  if (mobileOnlyPaths.length > 0) {
    console.log('\n⚠ 移动端独有路由 (' + mobileOnlyPaths.length + '):')
    mobileOnlyPaths.forEach((p) => console.log('  - /' + p))
  }

  if (mismatches.length > 0) {
    console.error('\n✗ 共有功能路径不一致 (' + mismatches.length + ' 项):')
    for (const p of mismatches) {
      console.error('  - ' + p.mobileName + ' <-> ' + p.pcName + ": PC '" + p.pcPath + "' vs 移动端 '" + p.mobilePath + "'")
    }
    process.exit(1)
  }

  console.log('\n✓ 共有功能路径一致（共享功能 ' + pairs.length + ' 项）')
  console.log('  (端独有路由为正常差异，不阻断构建)')
  process.exit(0)
}

main()

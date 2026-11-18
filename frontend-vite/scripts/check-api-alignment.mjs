#!/usr/bin/env node
/**
 * API 契约跨端一致性检查
 * 扫描 src/api/ 中定义的 API 端点，以及 src/mobile/ 中的直接 API 调用
 * 检测移动端是否绕过共享 API 层直接调用后端
 *
 * 用法: node scripts/check-api-alignment.mjs [--root <dir>]
 * 退出码: 0 = 一致, 1 = 发现绕过 API 层的直接调用, 2 = 扫描集合异常缩小（环境/目录问题）
 */
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
/**
 * 2026-10-17 审计 F2-1：扫描集合异常缩小必须报错。
 *
 * 原实现只看「命中了多少违规」，不看「扫到了多少文件」：`walkDir` 吞掉 readdir 异常后返回
 * `[]`，于是 `src/mobile` 改名/整体挪层时脚本仍打印「✓ 移动端所有 API 调用均通过共享 API 层」
 * 并 exit 0 —— 门禁静默退化成空转。下限取当前实测值的 ~80%。
 */
const MIN_MOBILE_FILES = 28
// 本脚本只扫 `.vue`（204 个，2026-11-18 实测）；310 是 check-pc-api-bypass 的口径（含 .ts）。
const MIN_PC_VIEW_FILES = 160

/** `--root <dir>`：只给夹具测试用（默认按脚本位置推断项目根）。 */
function parseRootArg(argv) {
  const eq = argv.find((a) => a.startsWith('--root='))
  if (eq) return resolve(eq.slice('--root='.length))
  const i = argv.indexOf('--root')
  if (i >= 0 && argv[i + 1]) return resolve(argv[i + 1])
  return null
}

const rootOverride = parseRootArg(process.argv.slice(2))
const srcDir = rootOverride ? join(rootOverride, 'src') : resolve(__dirname, '..', 'src')

function walkDir(dir, exts) {
  const results = []
  let entries
  try {
    entries = readdirSync(dir, { withFileTypes: true })
  } catch {
    return results
  }
  for (const entry of entries) {
    const fullPath = join(dir, entry.name)
    if (entry.isDirectory()) {
      results.push(...walkDir(fullPath, exts))
    } else if (entry.isFile()) {
      if (exts.some((ext) => entry.name.endsWith(ext))) {
        results.push(fullPath)
      }
    }
  }
  return results
}

function extractApiEndpoints(filePath) {
  let content
  try {
    content = readFileSync(filePath, 'utf-8')
  } catch {
    return new Set()
  }
  const endpoints = new Set()
  const patterns = [
    /(?:get|post|put|del|patch)<[^>]*>\s*\(\s*['"`]([^'"`]+)['"`]/g,
    /(?:get|post|put|del|patch)\s*\(\s*['"`]([^'"`]+)['"`]/g,
    /['"`](\/api\/v1\/[^'"`]+)['"`]/g,
  ]
  for (const regex of patterns) {
    let match
    while ((match = regex.exec(content)) !== null) {
      if (match[1] && !match[1].includes('${')) {
        endpoints.add(match[1])
      }
    }
  }
  return endpoints
}

const apiFiles = walkDir(join(srcDir, 'api'), ['.ts'])
const mobileFiles = walkDir(join(srcDir, 'mobile'), ['.ts', '.vue'])
const pcViewFiles = walkDir(join(srcDir, 'views'), ['.vue'])

// 2026-10-17 审计 F2-1：扫描集合异常缩小 → 退出码 2（与「有违规=1」区分）。
// 触发条件：目录被改名/整体挪层，或 walkDir 因权限问题吞掉异常返回空数组。
if (mobileFiles.length < MIN_MOBILE_FILES || pcViewFiles.length < MIN_PC_VIEW_FILES) {
  console.error(
    `[ERROR] 扫描集合异常缩小：src/mobile=${mobileFiles.length}（下限 ${MIN_MOBILE_FILES}）、`
    + `src/views=${pcViewFiles.length}（下限 ${MIN_PC_VIEW_FILES}）`,
  )
  console.error('  目录改名/挪层会让本门禁退化成空转；请同步更新脚本路径或下限后再跑。')
  process.exit(2)
}

const apiLayerEndpoints = new Set()
for (const file of apiFiles) {
  for (const ep of extractApiEndpoints(file)) {
    apiLayerEndpoints.add(ep)
  }
}

const mobileDirectCalls = new Map()
for (const file of mobileFiles) {
  const endpoints = extractApiEndpoints(file)
  for (const ep of endpoints) {
    if (!apiLayerEndpoints.has(ep)) {
      const relPath = relative(srcDir, file)
      if (!mobileDirectCalls.has(ep)) {
        mobileDirectCalls.set(ep, [])
      }
      mobileDirectCalls.get(ep).push(relPath)
    }
  }
}

console.log('=== API 契约一致性检查 ===')
console.log(`API 层定义端点数: ${apiLayerEndpoints.size}`)
console.log(`移动端文件数: ${mobileFiles.length}`)
console.log(`PC 端视图文件数: ${pcViewFiles.length}`)

if (mobileDirectCalls.size > 0) {
  console.warn(`\n⚠ 移动端绕过 API 层的直接调用 (${mobileDirectCalls.size}):`)
  for (const [ep, files] of mobileDirectCalls) {
    console.warn(`  ${ep}`)
    files.forEach((f) => console.warn(`    └─ ${f}`))
  }
  console.warn('\n建议: 将这些调用移至 src/api/ 共享层，确保两端 API 契约一致')
  process.exit(1)
}

console.log('\n✓ 移动端所有 API 调用均通过共享 API 层')
console.log('  (API 契约跨端一致)')
process.exit(0)

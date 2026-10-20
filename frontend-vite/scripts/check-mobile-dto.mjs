#!/usr/bin/env node
/**
 * 跨端 DTO 重复声明守卫（三条规则）。
 *
 * R1（既有）src/mobile 下不得重复声明 @/types（src/types/index.ts）已导出的后端 DTO。
 *      移动端视图必须复用共享数据层（@/api + @/types），不得自行复制后端 DTO 的字段
 *      定义 —— 复制出来的声明会与后端悄悄漂移（例如移动端自建 StockItem 里的
 *      safety_stock，后端库存接口根本不返回该字段，导致「低库存」筛选恒为假）。
 *
 * R2（2026-10-17 审计 F1-1）src/api/*.ts 不得重复声明 src/types/api.d.ts 里的类型。
 * R3（2026-10-17 审计 F1-2）src/types/index.ts 不得重复声明 src/types/api.d.ts 里的类型。
 *
 * 为什么加 R2/R3：api.d.ts 是「名义上的单一真相源」（由 openapi.json 生成），但手写层
 * 又把同名类型抄了一遍 —— src/api/*.ts 66 个 interface、src/types/index.ts 12 个，
 * 全仓只有 6 处 import 生成类型。两套同名定义各改各的，同构漂移已出过真实 bug
 * （移动端 StockItem.safety_stock 恒假）。此前**没有任何门禁**保证两套同步。
 *
 * 存量处理：R2/R3 的既有重复登记在 scripts/dto-duplicate-exemptions.json
 * （每条「相对路径:类型名」）。门禁只拦**新增**重复；登记项一旦失效（对应重复声明
 * 已不存在）同样判红 —— 逼着把豁免条目跟着迁移一起删掉，豁免表不能只增不减。
 *
 * 用法: node scripts/check-mobile-dto.mjs [--root <目录>]
 *   --root 用于在测试夹具上跑同一套规则（默认 = 本脚本所在仓库的前端目录）。
 * 退出码: 0 = 无重复声明, 1 = 发现重复声明 / 豁免条目失效
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootArgIndex = process.argv.indexOf('--root')
const root = rootArgIndex >= 0 ? resolve(process.argv[rootArgIndex + 1]) : resolve(__dirname, '..')
const typesFile = resolve(root, 'src', 'types', 'index.ts')
const generatedFile = resolve(root, 'src', 'types', 'api.d.ts')
const apiDir = resolve(root, 'src', 'api')
const mobileDir = resolve(root, 'src', 'mobile')
const exemptionFile = resolve(root, 'scripts', 'dto-duplicate-exemptions.json')

/** 取文件里声明的类型名（export interface X / export type X / interface X / type X） */
function declaredTypes(src) {
  const out = []
  src.split(/\r?\n/).forEach((line, i) => {
    const match = /^\s*(?:export\s+)?(?:interface|type)\s+(\w+)/.exec(line)
    if (match) out.push({ name: match[1], line: i + 1 })
  })
  return out
}

/** 归一化为「相对路径:类型名」，与豁免表的键一致 */
function keyOf(relPath, name) {
  return `${relPath}:${name}`
}

function walk(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else if (/\.(vue|ts)$/.test(entry)) out.push(full)
  }
  return out
}

// ===== R1：移动端重复声明 @/types 的 DTO =====
const dtoNames = new Set(
  [...readFileSync(typesFile, 'utf-8').matchAll(/export\s+interface\s+(\w+)/g)].map((m) => m[1]),
)

const violations = []
for (const file of walk(mobileDir)) {
  const lines = readFileSync(file, 'utf-8').split(/\r?\n/)
  lines.forEach((line, i) => {
    const match = /^\s*(?:export\s+)?(?:interface|type)\s+(\w+)/.exec(line)
    if (match && dtoNames.has(match[1])) {
      violations.push({ file: relative(root, file).replaceAll('\\', '/'), line: i + 1, name: match[1] })
    }
  })
}

if (violations.length > 0) {
  console.error('[FAIL] src/mobile 内重复声明了 @/types 的后端 DTO：')
  for (const v of violations) console.error(`  ${v.file}:${v.line}  ${v.name} → 请改为 import type { ${v.name} } from '@/types'`)
  console.error(`共 ${violations.length} 处。`)
  process.exit(1)
}

// ===== R2 / R3：手写层与生成层同名 =====
const generatedNames = new Set(
  [...readFileSync(generatedFile, 'utf-8').matchAll(/^export\s+(?:interface|type)\s+(\w+)/gm)].map((m) => m[1]),
)

/** 扫描目标：src/api/*.ts 与 src/types/index.ts */
const scanTargets = [
  ...readdirSync(apiDir)
    .filter((f) => f.endsWith('.ts'))
    .map((f) => join(apiDir, f)),
  typesFile,
]

const duplicates = []
for (const file of scanTargets) {
  const relPath = relative(root, file).replaceAll('\\', '/')
  for (const { name, line } of declaredTypes(readFileSync(file, 'utf-8'))) {
    if (generatedNames.has(name)) duplicates.push({ key: keyOf(relPath, name), file: relPath, line, name })
  }
}

// ===== 豁免表 =====
let exempted = new Set()
try {
  const payload = JSON.parse(readFileSync(exemptionFile, 'utf-8'))
  const entries = Array.isArray(payload) ? payload : payload.entries
  if (!Array.isArray(entries)) throw new Error('豁免表格式错误：应为数组或 { entries: [] }')
  for (const entry of entries) {
    if (typeof entry !== 'string' || !entry.includes(':')) {
      throw new Error(`豁免条目格式错误（应为「相对路径:类型名」）：${JSON.stringify(entry)}`)
    }
    exempted.add(entry)
  }
} catch (err) {
  console.error(`[FAIL] 豁免表不可读：${exemptionFile}`)
  console.error(`       ${err.message}`)
  process.exit(1)
}

const seen = new Set()
const unexempted = []
for (const dup of duplicates) {
  if (seen.has(dup.key)) continue
  seen.add(dup.key)
  if (!exempted.has(dup.key)) unexempted.push(dup)
}

const stale = [...exempted].filter((key) => !seen.has(key))

if (unexempted.length > 0 || stale.length > 0) {
  if (unexempted.length > 0) {
    console.error('[FAIL] 手写层重复声明了 @/types/api.d.ts（生成层）的同名类型：')
    for (const d of unexempted) {
      console.error(`  ${d.file}:${d.line}  ${d.name} → 请改为 import type { ${d.name} } from '@/types/api'`)
    }
    console.error(`共 ${unexempted.length} 处。`)
    console.error('       （确属存量重复的，请登记进 scripts/dto-duplicate-exemptions.json）')
  }
  if (stale.length > 0) {
    console.error('[FAIL] 豁免表里有条目已失效（对应重复声明已不存在）：')
    for (const key of stale) console.error(`  ${key} → 请从 scripts/dto-duplicate-exemptions.json 删除该条目`)
    console.error(`共 ${stale.length} 条。`)
  }
  process.exit(1)
}

console.log(
  `[PASS] src/mobile 无重复 DTO 声明（对照 @/types 的 ${dtoNames.size} 个导出接口）；` +
  `手写层无未登记的生成层同名类型（生成层 ${generatedNames.size} 个类型，登记豁免 ${exempted.size} 条）。`,
)

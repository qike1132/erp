#!/usr/bin/env node
/**
 * S12 移动端数据层守卫：禁止 src/mobile 下重复声明 @/types 已导出的后端 DTO。
 *
 * 移动端视图必须复用共享数据层（@/api + @/types），不得自行复制后端 DTO 的字段定义 ——
 * 复制出来的声明会与后端悄悄漂移（例如移动端自建 StockItem 里的 safety_stock，
 * 后端库存接口根本不返回该字段，导致「低库存」筛选恒为假）。
 *
 * 规则：src/mobile 下任何 interface / type 声明的名字若与 src/types/index.ts 的
 * 导出接口同名，即判为重复声明（组件自身的 UI 类型如 TabItem / ActionItem 不受影响）。
 *
 * 用法: node scripts/check-mobile-dto.mjs
 * 退出码: 0 = 无重复声明, 1 = 发现重复声明
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = resolve(__dirname, '..')
const typesFile = resolve(root, 'src', 'types', 'index.ts')
const mobileDir = resolve(root, 'src', 'mobile')

const dtoNames = new Set(
  [...readFileSync(typesFile, 'utf-8').matchAll(/export\s+interface\s+(\w+)/g)].map((m) => m[1]),
)

function walk(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else if (/\.(vue|ts)$/.test(entry)) out.push(full)
  }
  return out
}

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
console.log(`[PASS] src/mobile 无重复 DTO 声明（对照 @/types 的 ${dtoNames.size} 个导出接口）。`)

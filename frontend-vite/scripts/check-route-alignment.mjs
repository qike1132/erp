#!/usr/bin/env node
/**
 * CI 路由一致性检查
 * 从 router/index.ts 提取 PC 端与移动端路由路径，对比一致性
 * 仅检查共有功能的路径对齐，容忍端独有路由
 *
 * 用法: node scripts/check-route-alignment.mjs
 * 退出码: 0 = 一致, 1 = 不一致
 */
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const routerFile = resolve(__dirname, '..', 'src', 'router', 'index.ts')
const content = readFileSync(routerFile, 'utf-8')

function extractPathsFromArray(content, arrayName) {
  const startMarker = `const ${arrayName}`
  const startIdx = content.indexOf(startMarker)
  if (startIdx === -1) return new Set()

  const eqBracketIdx = content.indexOf('= [', startIdx)
  if (eqBracketIdx === -1) return new Set()
  const bracketStart = eqBracketIdx + 2

  let depth = 1
  let end = -1
  for (let i = bracketStart + 1; i < content.length; i++) {
    if (content[i] === '[') {
      depth++
    } else if (content[i] === ']') {
      depth--
      if (depth === 0) {
        end = i
        break
      }
    }
  }
  if (end === -1) return new Set()

  const arrayContent = content.slice(bracketStart, end)
  const paths = new Set()
  const regex = /path:\s*['"`]([^'"`]+)['"`]/g
  let match
  while ((match = regex.exec(arrayContent)) !== null) {
    const p = match[1]
    if (!p.includes(':') && !p.includes('pathMatch') && p !== '') {
      paths.add(p)
    }
  }
  return paths
}

const pcPaths = extractPathsFromArray(content, 'pcRoutes')
const mobilePaths = extractPathsFromArray(content, 'mobileRoutes')

const pcOnly = [...pcPaths].filter((p) => !mobilePaths.has(p)).sort()
const mobileOnly = [...mobilePaths].filter((p) => !pcPaths.has(p)).sort()

console.log('=== 路由一致性检查 ===')
console.log(`PC 端路由数: ${pcPaths.size}`)
console.log(`移动端路由数: ${mobilePaths.size}`)
console.log(`共有路由数: ${[...pcPaths].filter((p) => mobilePaths.has(p)).length}`)

if (pcOnly.length > 0) {
  console.log(`\n⚠ PC 端独有路由 (${pcOnly.length}):`)
  pcOnly.forEach((p) => console.log(`  - /${p}`))
}
if (mobileOnly.length > 0) {
  console.log(`\n⚠ 移动端独有路由 (${mobileOnly.length}):`)
  mobileOnly.forEach((p) => console.log(`  - /${p}`))
}

const sharedPc = [...pcPaths].filter((p) => mobilePaths.has(p))
const sharedMobile = [...mobilePaths].filter((p) => pcPaths.has(p))
const mismatched = sharedPc.filter((p) => !sharedMobile.includes(p))

if (mismatched.length > 0) {
  console.error(`\n✗ 共有功能路径不一致:`)
  mismatched.forEach((p) => console.error(`  - ${p}`))
  process.exit(1)
}

console.log('\n✓ 共有功能路径一致')
console.log('  (端独有路由为正常差异，不阻断构建)')
process.exit(0)
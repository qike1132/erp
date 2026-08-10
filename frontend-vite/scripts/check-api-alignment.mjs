#!/usr/bin/env node
/**
 * API 契约跨端一致性检查
 * 扫描 src/api/ 中定义的 API 端点，以及 src/mobile/ 中的直接 API 调用
 * 检测移动端是否绕过共享 API 层直接调用后端
 *
 * 用法: node scripts/check-api-alignment.mjs
 * 退出码: 0 = 一致, 1 = 发现绕过 API 层的直接调用
 */
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const srcDir = resolve(__dirname, '..', 'src')

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

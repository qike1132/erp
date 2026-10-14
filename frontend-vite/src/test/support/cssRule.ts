/**
 * 样式对齐契约测试的共用工具。
 *
 * 用途：把「A 组件的样式声明必须与参照组件逐条一致」这类不变量写成可执行断言，
 * 而不是只写在注释里（参照 src/test/zLayers.test.ts 的源码不变量风格）。
 */
import { readFileSync } from 'node:fs'

/** 读取仓库内文件（相对 frontend-vite 工作目录） */
export function readSfc(relPath: string): string {
  return readFileSync(relPath, 'utf8')
}

/** 取出一条样式规则的声明集合（属性 → 值，按属性名排序，便于整体比较） */
export function cssRule(source: string, selector: string): [string, string][] {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const m = source.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))
  if (!m) throw new Error(`未找到样式规则 ${selector}`)
  const decls = new Map<string, string>()
  for (const part of (m[1] ?? '').split(';')) {
    const text = part.trim()
    if (!text) continue
    const idx = text.indexOf(':')
    decls.set(text.slice(0, idx).trim(), text.slice(idx + 1).trim())
  }
  return [...decls.entries()].sort()
}

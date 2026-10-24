/**
 * 样式对齐契约测试的共用工具。
 *
 * 用途：把「A 组件的样式声明必须与参照组件逐条一致」这类不变量写成可执行断言，
 * 而不是只写在注释里（参照 src/test/zLayers.test.ts 的源码不变量风格）。
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, parse } from 'node:path'

/**
 * 读取仓库内文件（相对 frontend-vite 工作目录）。
 *
 * SFC 的 <style scoped src="./X.css"> 外部样式形态（F1b-08 批次引入）会把
 * 规则搬出 .vue 文件——源码级样式契约测试必须把同名 .css 拼回去，否则
 * cssRule 找不到声明。非 SFC 或无同名 css 时行为不变。
 */
export function readSfc(relPath: string): string {
  const source = readFileSync(relPath, 'utf8')
  if (!relPath.endsWith('.vue')) return source
  const cssPath = join(dirname(relPath), parse(relPath).name + '.css')
  if (!existsSync(cssPath)) return source
  const css = readFileSync(cssPath, 'utf8')
  return source.replace(/<style scoped src="[^"]+"><\/style>/, `<style scoped>\n${css}\n</style>`)
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

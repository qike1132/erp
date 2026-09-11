/**
 * swap-dist.mjs — 原子化替换 dist（配合 `build:atomic` 使用）
 *
 * vite 构建默认 `emptyOutDir` 会先清空 dist 再写入，期间 nginx 直指 dist，
 * 用户访问会出现"旧 index.html 引用旧 hash 资源 → 404 → 启动遮罩永久加载中"。
 * 这里改为：构建产物输出到 dist-new，再用「重命名交换」一次切换，窗口极短且可回退。
 *
 * 用法：npm run build:atomic  （构建到 dist-new 后自动执行本脚本）
 */
import { rename, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')
const dist = join(root, 'dist')
const distNew = join(root, 'dist-new')
const distOld = join(root, 'dist-old')

if (!existsSync(distNew)) {
  console.error('[swap-dist] 未找到 dist-new（请先运行 vite build --outDir dist-new）')
  process.exit(1)
}

// 清理上次遗留的 dist-old，避免无限堆积
await rm(distOld, { recursive: true, force: true })

// 当前 dist → dist-old（保留作回退），dist-new → dist（一次重命名切换）
// 若中途失败（如防病毒锁定 dist-new），回滚：把 dist-old 恢复为 dist，避免线上 404。
try {
  if (existsSync(dist)) {
    await rename(dist, distOld)
  }
  await rename(distNew, dist)
} catch (err) {
  console.error('[swap-dist] 替换失败，正在回滚:', err)
  if (existsSync(distOld) && !existsSync(dist)) {
    await rename(distOld, dist)
  }
  process.exit(1)
}
await rm(distOld, { recursive: true, force: true })

console.log('[swap-dist] dist 已原子化替换完成')

/**
 * vite-build.mjs — 带 esbuild 规避的 `vite build` 包装器。
 *
 * 背景（2026-10-02 实测）：本机 `D:\erp_system` 下的可执行文件，其"删除 %TEMP% 文件"
 * 的操作被系统拒绝。esbuild 处理 **>1MB** 的 transform 输入时，会把输入落盘成临时文件
 * 再删除（esbuild `lib/main.js` 硬编码阈值 `input.length > 1024*1024`），删除被拒 →
 * 构建失败：`[vite:esbuild-transpile] remove ...\Temp\esbuild-<hex>: Access is denied`。
 *
 * 规避：把平台 esbuild 二进制复制到**项目之外**（系统临时目录），用
 * `ESBUILD_BINARY_PATH` 指向该副本，再跑 vite。副本文件名含 esbuild 版本号，
 * 升级 esbuild 后自动重建副本，避免二进制与 JS 版本错配。
 *
 * 仅 Windows 生效；其它平台/已显式设置时原样转发给 vite。
 *
 * 用法：node scripts/vite-build.mjs [vite build 的参数...]
 */
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { copyFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const env = { ...process.env }

function resolveEsbuildExe(version) {
  try {
    return require.resolve('@esbuild/win32-x64/esbuild.exe')
  } catch {
    return join(dirname(require.resolve('esbuild/package.json')), '..', '@esbuild', 'win32-x64', 'esbuild.exe')
  }
}

if (process.platform === 'win32' && !env.ESBUILD_BINARY_PATH) {
  try {
    const version = require('esbuild/package.json').version
    const src = resolveEsbuildExe(version)
    const dir = join(tmpdir(), 'esbuild-host-fix')
    mkdirSync(dir, { recursive: true })
    const dst = join(dir, `esbuild-${version}.exe`)
    if (!existsSync(dst)) copyFileSync(src, dst)
    env.ESBUILD_BINARY_PATH = dst
    console.error(`[vite-build] ESBUILD_BINARY_PATH=${dst}`)
  } catch (e) {
    console.error('[vite-build] 未能设置 ESBUILD_BINARY_PATH，按默认继续:', e instanceof Error ? e.message : e)
  }
}

function resolveViteBin() {
  const candidates = []
  try {
    const pkgPath = require.resolve('vite/package.json')
    const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'))
    const rel = typeof pkg.bin === 'string' ? pkg.bin : pkg.bin.vite
    candidates.push(join(dirname(pkgPath), rel))
  } catch {
    /* vite 的 exports 可能不暴露 ./package.json，走下面的兜底 */
  }
  candidates.push(join(dirname(fileURLToPath(import.meta.url)), '..', 'node_modules', 'vite', 'bin', 'vite.js'))
  return candidates.find(existsSync)
}

const viteBin = resolveViteBin()
if (!viteBin) {
  console.error('[vite-build] 找不到 vite CLI')
  process.exit(1)
}

const result = spawnSync(process.execPath, [viteBin, 'build', ...process.argv.slice(2)], {
  stdio: 'inherit',
  env,
})
process.exit(result.status ?? 1)

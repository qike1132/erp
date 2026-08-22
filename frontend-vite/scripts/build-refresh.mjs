/**
 * build-refresh.mjs — 构建 + 自动刷新浏览器
 *
 * 用法:
 *   node scripts/build-refresh.mjs [url] [--fast]
 *
 * 说明:
 *   - 构建: 默认 `npm run build`(含 vue-tsc 类型检查); 传 `--fast` 用 `build:fast`(跳过类型检查, 更快)
 *   - 刷新: 构建成功后用系统默认浏览器打开指定 url。同一浏览器 profile 保留登录 cookie,
 *     若该标签已存在, 多数浏览器会聚焦并重新加载, 达到"自动刷新"效果。
 *   - 默认 url 为打样页(当前工作对象); 也可显式传入其它页面或网关地址。
 */
import { execSync } from 'node:child_process'
import { platform } from 'node:os'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'

const here = dirname(fileURLToPath(import.meta.url))
const args = process.argv.slice(2)

// 解析 url 与 --fast
const fast = args.includes('--fast')
let url = args.find((a) => a.startsWith('http'))
  ?? 'http://192.168.0.95:3000/pattern-room'

const buildCmd = fast ? 'npm run build:fast' : 'npm run build'
console.log(`[1/2] 构建: ${buildCmd}`)
execSync(buildCmd, { stdio: 'inherit', cwd: here })

console.log(`[2/2] 打开浏览器: ${url}`)
try {
  if (platform() === 'win32') {
    // Windows: 用系统 start 打开默认浏览器(保留会话 cookie)
    spawn('cmd', ['/c', 'start', '', url], {
      stdio: 'ignore', detached: true, shell: false,
    }).unref()
  } else if (platform() === 'darwin') {
    spawn('open', [url], { stdio: 'ignore', detached: true }).unref()
  } else {
    spawn('xdg-open', [url], { stdio: 'ignore', detached: true }).unref()
  }
} catch (err) {
  console.error('打开浏览器失败, 请手动访问: ' + url)
  console.error(err)
}
/**
 * swap-dist.mjs — 原子化替换 dist（配合 `build:atomic` 使用）
 *
 * vite 构建默认 `emptyOutDir` 会先清空 dist 再写入，期间 nginx 直指 dist，
 * 用户访问会出现"旧 index.html 引用旧 hash 资源 → 404 → 启动遮罩永久加载中"。
 * 这里改为：构建产物输出到 dist-new，再用「重命名交换」一次切换，切换窗口极短。
 *
 * ⚠️ 关于「可回退」的准确表述（2026-09-17 审计 H6）
 * ---------------------------------------------------------------------------
 * 回滚副本只在**交换过程的 try 块内**存在；一旦交换成功，**本脚本会立刻删除
 * dist-old**（见文件末尾的 rm），因此**发布成功后并没有可回退的副本**。
 * 需要回滚能力请自行在发布前备份，例如：
 *     cp -r frontend-vite/dist backups/frontend-dist-$(date +%Y%m%d-%H%M%S)
 * 回滚方式：把备份改回 dist。
 *
 * ⚠️ 关于 `EPERM rename dist-new → dist` 的**真实根因**（勿再归因防病毒）
 * ---------------------------------------------------------------------------
 * 真因是 **vite dev server 的 chokidar watcher 持有 `dist-new` 的目录句柄**：
 * vite 只忽略 `build.outDir`（默认 dist），**不忽略 dist-new**。
 * 实测证据：`rename(dist, dist.__probe)` 成功，而 `rename(dist-new, …)` 抛
 * `PermissionError errno=13`。
 * 两种可行解法：
 *   ① 先停 dev server 再换 dist（即「停开发 → 换 dist → 起服务」的顺序）；
 *   ② 把产物先 copytree 到 **vite root 之外**的暂存目录（如 D:\erp_system\_dist_stage），
 *      再 rename 到 `frontend-vite/dist` —— 源在 watch 树之外，无锁；目标是 dist，被忽略。
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

// 当前 dist → dist-old（**仅在交换过程中**临时充当回退源），dist-new → dist（一次重命名切换）
// 若中途失败（最常见：vite dev server watcher 持有 dist-new 句柄导致 EPERM rename，
// 见文件头说明；**不是**防病毒锁定），回滚：把 dist-old 恢复为 dist，避免线上 404。
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
// ⚠️ 破坏性动作：交换成功后立即删除唯一的回退副本。
// 这就是"发布成功后已无可回退副本"的原因 —— 需要回滚请在发布前自行备份。
await rm(distOld, { recursive: true, force: true })
console.log('[swap-dist] 已删除临时回退副本 dist-old（发布成功后无可回退副本，需回滚请用发布前备份）')

console.log('[swap-dist] dist 已原子化替换完成')

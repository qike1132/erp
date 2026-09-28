/**
 * swap-dist.mjs — 原子化替换 dist（配合 `build:atomic` 使用）
 *
 * vite 构建默认 `emptyOutDir` 会先清空 dist 再写入，期间 nginx 直指 dist，
 * 用户访问会出现"旧 index.html 引用旧 hash 资源 → 404 → 启动遮罩永久加载中"。
 * 这里改为：构建产物输出到 dist-new，再用「重命名交换」一次切换，切换窗口极短。
 *
 * ⚠️ `EPERM rename` 的根因与修复（2026-09-28 补齐，此前只有现象描述）
 * ---------------------------------------------------------------------------
 * 根因：**vite dev server 的 chokidar watcher 持有 `dist-new` 的目录句柄**。
 * vite 的 `resolveChokidarOptions()` 只在 `emptyOutDir` 为真时把 build.outDir 追加进
 * `ignored`；而 `build:atomic` 的 `--outDir dist-new` 是 **CLI 参数**，dev server 解析不到
 * （它看到的是默认 `dist`）→ 于是只忽略 dist、不忽略 dist-new。
 * 实测：`rename(dist, …)` 成功，`rename(dist-new, …)` 抛 errno=13。
 *
 * 修复：`vite.config.ts` 的 `server.watch.ignored` 已显式排除
 * dist-new / dist-old / dist-old-swap / dist_prev_*（vite 的 ignored 是**追加**语义，
 * 不覆盖默认项）。故现在 dev server 运行时也能直接交换，无需「先停 dev server」。
 * ⚠️ 若以后改暂存目录名，**必须同步往那里加一行**，否则本脚本会重新 EPERM。
 *
 * 兜底（不依赖上面的修复）：交换失败时回滚「rename 优先、失败则递归复制」——复制不受
 * 句柄锁影响；两者都失败才退出，且此时**不删任何目录**并打印手工恢复步骤。
 * 2026-09-28 之前这里只有 rename 一种回滚，于是回滚被锁时 `dist` 会直接消失。
 *
 * ⚠️ 关于「可回退」的准确表述（2026-09-17 审计 H6）
 * ---------------------------------------------------------------------------
 * 回滚副本只在**交换过程的 try 块内**存在；一旦交换成功，**本脚本会立刻删除
 * dist-old**（见文件末尾的 rm），因此**发布成功后并没有可回退的副本**。
 * 需要回滚能力请自行在发布前备份，例如：
 *     cp -r frontend-vite/dist backups/frontend-dist-$(date +%Y%m%d-%H%M%S)
 * 回滚方式：把备份改回 dist。
 *
 * 用法：npm run build:atomic  （构建到 dist-new 后自动执行本脚本）
 */
import { rename, rm, cp } from 'node:fs/promises'
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
// 先验源再动目标：宁可拒绝交换，也不要先把 dist 挪走才发现新包是空的
if (!existsSync(join(distNew, 'index.html'))) {
  console.error('[swap-dist] dist-new 不完整（缺 index.html），拒绝交换，dist 保持原样')
  process.exit(1)
}

// 清理上次遗留的 dist-old，避免无限堆积
await rm(distOld, { recursive: true, force: true })

/** 回滚：rename 优先（快、原子），失败则递归复制（复制不受 watcher/AV 句柄锁影响）。 */
async function restoreDist() {
  if (existsSync(dist) || !existsSync(distOld)) return
  try {
    await rename(distOld, dist)
    return
  } catch (err) {
    console.error('[swap-dist] 回滚 rename 失败，改用复制兜底:', err)
  }
  await cp(distOld, dist, { recursive: true })
}

// 当前 dist → dist-old（仅在交换过程中临时充当回退源），dist-new → dist（一次重命名切换）
try {
  if (existsSync(dist)) {
    await rename(dist, distOld)
  } else {
    console.warn('[swap-dist] ⚠️ 起始状态没有 dist，本次交换无可回退副本')
  }
  await rename(distNew, dist)
} catch (err) {
  console.error('[swap-dist] 替换失败，正在回滚:', err)
  try {
    await restoreDist()
  } catch (rollbackErr) {
    console.error('[swap-dist] ❌ 回滚失败，dist 当前缺失（未删除任何目录）:', rollbackErr)
    console.error('[swap-dist] 手工恢复：')
    console.error('  1) 停掉 dev server 释放 watcher 句柄；或确认 vite.config.ts 的 server.watch.ignored 覆盖了构建暂存目录名')
    console.error(`  2) 把 ${distOld} 改名或复制为 ${dist}`)
    console.error('  3) 重跑 npm run build:atomic')
    process.exit(2)
  }
  process.exit(1)
}

// ⚠️ 破坏性动作：交换成功后立即删除唯一的回退副本。
// 这就是"发布成功后已无可回退副本"的原因 —— 需要回滚请在发布前自行备份。
await rm(distOld, { recursive: true, force: true })
console.log('[swap-dist] 已删除临时回退副本 dist-old（发布成功后无可回退副本，需回滚请用发布前备份）')

console.log('[swap-dist] dist 已原子化替换完成')

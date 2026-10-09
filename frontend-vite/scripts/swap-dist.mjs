/**
 * swap-dist.mjs — 把 dist-new 的内容「有序复制」进 dist（配合 `npm run build:atomic`）
 *
 * 背景
 * ---------------------------------------------------------------------------
 * vite build 默认 `emptyOutDir` 会先清空 dist 再写入；期间 nginx 直指 dist，用户会撞到
 * 「旧 index.html 引用已被清掉的旧资源 → 404 → 启动遮罩永久加载中」。
 * 旧版脚本用「重命名交换」（dist→dist-old，dist-new→dist）来缩短窗口，但见下。
 *
 * ⚠️ 为什么弃用 rename（2026-10-09 改）
 * ---------------------------------------------------------------------------
 * Windows 下对目录做 rename 会被句柄锁顶成 EPERM（errno=13 / -4048）：nginx 常驻持有
 * `dist` 句柄，dev server / 编辑器索引器的 chokidar 也可能持有 `dist-new`。旧脚本虽在
 * 失败时回滚，但若回滚的 rename 也失败，`dist` 会**直接消失**（2026-09-28 真实发生过），
 * 而复制**不受目录句柄锁影响**。
 *
 * 现方案：有序复制（dist 全程存在、任何时刻都可服务）
 * ---------------------------------------------------------------------------
 *   1) 先复制除 index.html 外的全部顶层条目（assets 优先）
 *   2) 最后复制 index.html
 *   3) 再剪掉 dist 里已不在 dist-new 中的残留
 * 关键在**第 2 步最后换 index.html**：换之前 live index.html 仍指向旧资源（旧资源还在，
 * 因剪枝在第 3 步）；换之后它指向的新资源**已全部就位**。故任何时刻都不会出现
 * 「index.html 引用了不存在的资源」。中途失败也不打坏线上（旧 index.html + 旧资源仍在），
 * 重跑本脚本即可续上。
 *
 * ⚠️ 关于「可回退」：发布成功后**没有**可回退副本（本脚本不保留 dist-old）。需要回滚请在
 * 发布前自行备份：
 *     cp -r frontend-vite/dist backups/frontend-dist-$(date +%Y%m%d-%H%M%S)
 *   回滚方式：把备份复制回 dist。
 *
 * 用法：npm run build:atomic  （构建到 dist-new 后自动执行本脚本）
 */
import { cp, rm, mkdir, readdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')
const dist = join(root, 'dist')
const distNew = join(root, 'dist-new')

if (!existsSync(distNew)) {
  console.error('[swap-dist] 未找到 dist-new（请先运行 vite build --outDir dist-new）')
  process.exit(1)
}
// 先验源再动目标：宁可拒绝替换，也不要先清 dist 才发现新包是空的
if (!existsSync(join(distNew, 'index.html'))) {
  console.error('[swap-dist] dist-new 不完整（缺 index.html），拒绝替换，dist 保持原样')
  process.exit(1)
}

/** 复制单个顶层条目；对瞬时 EPERM/EBUSY（nginx 或索引器正读该文件）重试几次。 */
async function copyEntry(name) {
  for (let attempt = 1; ; attempt++) {
    try {
      await cp(join(distNew, name), join(dist, name), { recursive: true, force: true })
      return
    } catch (err) {
      if (attempt >= 4 || (err.code !== 'EPERM' && err.code !== 'EBUSY')) throw err
      await new Promise((resolve) => setTimeout(resolve, 200 * attempt))
    }
  }
}

/** 删除 dir 里不在 keep 集合中的残留（发布后剪枝，避免旧资源无限堆积）。 */
async function prune(dir, keep) {
  if (!existsSync(dir)) return
  for (const name of await readdir(dir)) {
    if (!keep.has(name)) await rm(join(dir, name), { recursive: true, force: true })
  }
}

await mkdir(dist, { recursive: true })

// 除 index.html 外的顶层条目：assets 优先，其余次之；index.html 留到最后单独复制
const others = (await readdir(distNew)).filter((name) => name !== 'index.html')
others.sort((a, b) => (a === 'assets' ? -1 : b === 'assets' ? 1 : 0))

try {
  for (const name of others) await copyEntry(name)
  // 最后换 index.html：此刻它引用的新资源已全部就位
  await copyEntry('index.html')
} catch (err) {
  console.error('[swap-dist] ❌ 复制失败，dist 未被打坏（旧 index.html + 旧资源仍在）:', err)
  console.error('[swap-dist] 排查占用后重跑 npm run build:atomic 即可续上')
  process.exit(1)
}

// 剪枝：顶层 + assets/ 里已不在新构建中的残留。
// 剪枝失败不应导致整次发布报错退出：新内容已全部就位，残留旧文件只是
// 占磁盘（旧 hash 文件名不会被引用），删不掉下次构建还会再试。
for (const [dir, keep] of [
  [dist, new Set([...others, 'index.html'])],
  ...(existsSync(join(distNew, 'assets'))
    ? [[join(dist, 'assets'), new Set(await readdir(join(distNew, 'assets')))]]
    : []),
]) {
  try {
    await prune(dir, keep)
  } catch (err) {
    console.warn('[swap-dist] ⚠️ 剪枝失败（不影响发布，残留旧文件下次构建再清）:', err?.message ?? err)
  }
}

console.log('[swap-dist] dist 已有序复制替换完成（发布成功后无可回退副本，需回滚请用发布前备份）')

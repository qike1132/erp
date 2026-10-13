/**
 * prune-dist-backups.mjs — 发布成功后清理历史前端 dist 备份（配合 `npm run build:atomic`）
 *
 * 背景
 * ---------------------------------------------------------------------------
 * swap-dist.mjs 不留回退副本，文档要求发布前自行备份到 backups/（或历史 rename
 * 时代的 dist_prev_*）。但「只备份不清理」让备份从 2026-09-11 起日积月累到 65 份
 * 约 280MB（2026-10-11 手工清理过一次）。本脚本把清理接进发布链，一次解决。
 *
 * 策略
 * ---------------------------------------------------------------------------
 * - 备份目录 candidates：backups/frontend-dist* 与 frontend-vite/dist_prev_*、
 *   dist-old-swap（历史 rename 交换残留）、dist-new（构建中间产物）
 * - 每自然日保留**最后一份**：同日多份发布只留当天**时间最晚**的一份（按目录名里的
 *   时间戳排序，不是目录 mtime）；今天发布刚做的备份是当前线上的回滚锚点，必留
 *   （它就是今天最后一份，天然满足）
 * - 时间戳按真实时间比较：`YYYYMMDD-HHMMSS`（发布前备份）与 `YYYYMMDD_HHMM`
 *   （历史 rename 时代，4 位时间补 :00 秒）同尺度归一化后再排序；只有日期的视为当天最末
 * - **最近 N 天**（默认 7）之外全删；目录名无日期的跳过（宁留勿删）
 * - 删除失败不阻断发布（新内容已上线，旧备份只是占磁盘），仅警告
 *
 * 用法：node scripts/prune-dist-backups.mjs [--days 7] [--dry-run]
 */
import { readdirSync, rmSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const frontendRoot = join(here, '..')
const projectRoot = join(frontendRoot, '..')
const backupsDir = join(projectRoot, 'backups')

/**
 * 目录名里的时间戳 → 归一化成 `YYYYMMDD_HHMMSS`（可直接字符串比较排序）；取不到返回 null。
 * 支持 `YYYYMMDD-HHMMSS` / `YYYYMMDD_HHMMSS`、`YYYYMMDD_HHMM`（4 位补 :00 秒）与纯日期
 * （视为当天最末 235959，保留侧更保守）。
 */
export function parseStamp(name) {
  const full = name.match(/(\d{8})[-_]?(\d{6})/)
  if (full) return full[1] + '_' + full[2]
  // 历史 rename 时代 dist_prev_YYYYMMDD_HHMM 只有 4 位时间；补 :00 秒后才能与 6 位同尺度比较，
  // 否则会降级成「只有日期」→ 归一化成当天 235959 → 反而击败当天真正更晚的备份（2026-10-13 事故）。
  const short = name.match(/(\d{8})[-_]?(\d{4})(?!\d)/)
  if (short) return short[1] + '_' + short[2] + '00'
  const day = name.match(/(\d{8})/)
  return day ? day[1] + '_235959' : null // 只有日期的视为当天最末（保留侧更保守）
}

/** 备份路径 → 其目录名（跨平台：同时处理 / 与 \）。 */
const baseName = (p) => p.split(/[\\/]/).pop()

/**
 * 按「每自然日保留时间最晚一份、窗口外整天删」算出应删清单（纯函数，不碰文件系统，便于测试）。
 * @returns {{ drop: string[], cutoffDay: string }}
 */
export function selectBackupsToDrop(candidates, { days, now = new Date() }) {
  const cutoff = new Date(now)
  cutoff.setDate(cutoff.getDate() - (days - 1)) // 含今天共 N 天
  const cutoffDay = `${cutoff.getFullYear()}${String(cutoff.getMonth() + 1).padStart(2, '0')}${String(cutoff.getDate()).padStart(2, '0')}`

  const byDay = new Map()
  for (const p of candidates) {
    const stamp = parseStamp(baseName(p))
    if (!stamp) continue // 无日期戳（如 dist-old-swap）→ 宁留勿删，需人工处置
    const day = stamp.slice(0, 8)
    if (!byDay.has(day)) byDay.set(day, [])
    byDay.get(day).push([stamp, p])
  }

  const drop = []
  for (const [day, items] of byDay) {
    items.sort((a, b) => (a[0] < b[0] ? -1 : 1))
    for (let i = 0; i < items.length; i++) {
      const isLastOfDay = i === items.length - 1
      // 窗口外整天删（含该日最后一份）；窗口内只删同日非最后一份
      if (day < cutoffDay || !isLastOfDay) drop.push(items[i][1])
    }
  }
  return { drop, cutoffDay }
}

function main() {
  const args = process.argv.slice(2)
  const argVal = (flag, dflt) => {
    const i = args.indexOf(flag)
    return i >= 0 && args[i + 1] ? Number(args[i + 1]) : dflt
  }
  const dryRun = args.includes('--dry-run')
  const days = argVal('--days', 7)
  if (!Number.isFinite(days) || days < 1) {
    console.error('[prune-backups] --days 须为 >=1 的数字')
    process.exit(1)
  }

  // 收集候选：backups/frontend-dist* + frontend-vite/dist_prev_* / dist-old-swap / dist-new
  const candidates = []
  if (existsSync(backupsDir)) {
    for (const name of readdirSync(backupsDir)) {
      if (name.startsWith('frontend-dist')) candidates.push(join(backupsDir, name))
    }
  }
  for (const name of ['dist-old-swap', 'dist-new']) {
    const p = join(frontendRoot, name)
    if (existsSync(p)) candidates.push(p) // 无日期戳 → parseStamp 为 null → 跳过（见下）
  }
  for (const name of readdirSync(frontendRoot)) {
    if (name.startsWith('dist_prev_')) candidates.push(join(frontendRoot, name))
  }

  // dist-new 是构建中间产物（swap 已完成即残留），无条件清，不受日期策略管
  const distNew = join(frontendRoot, 'dist-new')
  if (existsSync(distNew) && !dryRun) {
    rmSync(distNew, { recursive: true, force: true })
    console.log('[prune-backups] 已清理构建中间产物 dist-new')
  }

  const { drop, cutoffDay } = selectBackupsToDrop(candidates, { days })

  let freed = 0
  let removed = 0
  for (const p of drop) {
    if (dryRun) {
      console.log(`[prune-backups] DRYRUN 将删 ${p}`)
    } else {
      try {
        rmSync(p, { recursive: true, force: true })
        removed++
      } catch (err) {
        console.warn(`[prune-backups] ⚠️ 删除失败（不阻断发布）: ${p}: ${err?.message ?? err}`)
        continue
      }
    }
    freed++
  }

  console.log(
    `[prune-backups] ${dryRun ? 'DRYRUN ' : ''}窗口 ${cutoffDay} 起 ${days} 天：清理 ${freed} 份` +
      (removed ? `（实际删除 ${removed}）` : ''),
  )
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()

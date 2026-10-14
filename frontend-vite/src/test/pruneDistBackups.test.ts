import { describe, it, expect } from 'vitest'
import { parseStamp, selectBackupsToDrop } from '../../scripts/prune-dist-backups.mjs'

// 回归背景（2026-10-13 真实事故）：
// 发布前按文档备份成 backups/frontend-dist-YYYYMMDD-HHMMSS，同机还残留历史 rename 时代的
// frontend-vite/dist_prev_YYYYMMDD_HHMM（4 位时间）。parseStamp 曾把 4 位时间降级成「只有日期」
// 并归一化为当天 23:59:59，于是在「每自然日保留最后一份」里击败了当天真正更晚的备份，把发布前
// 刚做的回滚锚点删掉。以下用例锁死：同日按真实时间排序，当天最新一份（锚点）不被删。

describe('parseStamp：备份目录名时间戳归一化', () => {
  it('6 位时间 frontend-dist-YYYYMMDD-HHMMSS 原样归一化', () => {
    expect(parseStamp('frontend-dist-20261013-090949')).toBe('20261013_090949')
  })

  it('4 位时间（历史 dist_prev_YYYYMMDD_HHMM）补 :00 秒', () => {
    expect(parseStamp('dist_prev_20261013_0806')).toBe('20261013_080600')
  })

  it('纯日期目录视为当天最末 235959', () => {
    expect(parseStamp('frontend-dist-20261013')).toBe('20261013_235959')
  })

  it('无日期戳返回 null（宁留勿删）', () => {
    expect(parseStamp('dist-old-swap')).toBeNull()
    expect(parseStamp('dist-new')).toBeNull()
  })
})

describe('同日排序：按真实时间，晚者排后', () => {
  it('08:06 的 dist_prev 排在 09:09 的 frontend-dist 之前', () => {
    const sorted = ['dist_prev_20261013_0806', 'frontend-dist-20261013-090949'].map((n) => parseStamp(n)).sort()
    expect(sorted).toEqual(['20261013_080600', '20261013_090949'])
  })
})

describe('selectBackupsToDrop：当天最新备份（回滚锚点）不被删', () => {
  const now = new Date('2026-10-13T12:00:00')

  it('同日：删较早的 dist_prev，保留当天最新 frontend-dist', () => {
    const candidates = [
      '/x/backups/frontend-dist-20261013-090949',
      '/x/frontend-vite/dist_prev_20261013_0806',
    ]
    const { drop } = selectBackupsToDrop(candidates, { days: 7, now })
    expect(drop).toEqual(['/x/frontend-vite/dist_prev_20261013_0806'])
  })

  it('窗口外整天删（含该日最后一份）', () => {
    const candidates = ['/x/backups/frontend-dist-20261001-080000']
    const { drop } = selectBackupsToDrop(candidates, { days: 7, now })
    expect(drop).toEqual(['/x/backups/frontend-dist-20261001-080000'])
  })

  it('无日期戳目录从不进入删除清单', () => {
    const candidates = ['/x/frontend-vite/dist-old-swap']
    const { drop } = selectBackupsToDrop(candidates, { days: 7, now })
    expect(drop).toEqual([])
  })
})

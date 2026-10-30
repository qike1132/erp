/**
 * backupApi.asyncImport 不得硬编码 confirm=true（2026-10-30 审计 A-H4）。
 *
 * 旧实现把 confirm:'true' 写死在 API 层，任何调用方（含「选文件即还原」入口）
 * 都绕过前端确认流；修复后必须由调用方在完成确认后显式传 confirm。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  upload: vi.fn().mockResolvedValue({ success: true }),
  download: vi.fn(),
}))

import { upload } from '@/api/request'
import { backupApi } from '@/api/backup'

const uploadMock = vi.mocked(upload)

describe('backupApi.asyncImport 确认闸门（A-H4）', () => {
  beforeEach(() => {
    uploadMock.mockClear()
  })

  it('未显式确认时不带 confirm=true', async () => {
    await backupApi.asyncImport(new FormData())
    const url = String(uploadMock.mock.calls[0]?.[0] ?? '')
    expect(url).not.toContain('confirm=true')
  })

  it('显式传 confirm 时才放行', async () => {
    await backupApi.asyncImport(new FormData(), { confirm: true })
    const url = String(uploadMock.mock.calls[0]?.[0] ?? '')
    expect(url).toContain('confirm=true')
  })
})

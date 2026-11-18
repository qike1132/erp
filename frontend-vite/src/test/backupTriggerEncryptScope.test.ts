/**
 * 备份触发时的加密意图必须跟随超管身份（2026-11-18 评审 High1）。
 *
 * 背景：`POST /backup/full` 与 `GET /backup/export-info` 在「本次会加密」时要求
 * 调用者是超管 —— 因为加密包会打包现役 JWT 私钥与运行时 `.env`
 * （后端 `require_superuser_for_encrypted_backup`）。生产 `.env` 里
 * `BACKUP_ENCRYPTION_ENABLED=true`，所以只要 UI 无脑传 `encrypt: true`，
 * **非超管点「备份」必然 403**，而界面没有任何补救路径。
 *
 * 这条用例锁死取舍：超管传 true（拿完整加密包），非超管传 false（拿明文包，
 * 明文包已排除敏感配置）。两者都不该被 403 挡住。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

// vi.mock 会被提升，状态必须放在 vi.hoisted 里
const h = vi.hoisted(() => ({
  isSuper: false,
  triggerFull: vi.fn(
    async (_payload: { encrypt: boolean; password?: string }) => ({ task_id: 't-1' }),
  ),
}))

vi.mock('@/stores/auth', () => ({
  // 用 getter 让每次调用都读当前值
  useAuthStore: () => ({ user: { get is_super() { return h.isSuper } } }),
}))

vi.mock('@/api', () => ({
  backupApi: {
    triggerFull: h.triggerFull,
    getStatus: vi.fn(async () => ({})),
    getRecords: vi.fn(async () => ({ records: [], total: 0 })),
    getSchedule: vi.fn(async () => ({ schedules: [] })),
    listSchedules: vi.fn(async () => ({ schedules: [] })),
    getSettings: vi.fn(async () => ({})),
  },
}))

vi.mock('@/composables/useToast', () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}))

vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: vi.fn(async () => true) }),
}))

vi.mock('@/components/backup/composables/useBackupTask', async () => {
  const { ref } = await import('vue')
  return { useBackupTask: () => ({ state: ref(null) }) }
})

import BackupView from '@/views/backup/BackupView.vue'

interface BackupVm {
  triggerFull: (opts?: { password?: string }) => Promise<void>
}

function mountView() {
  return mount(BackupView, {
    global: {
      stubs: {
        BackupOverviewCards: true,
        BackupActions: true,
        ScheduleConfig: true,
        PathSettings: true,
        BackupRecordTable: true,
        RestoreConfirmDialog: true,
        UiConfirmDialog: true,
      },
    },
  })
}

describe('手动全量备份的 encrypt 意图跟随超管身份', () => {
  beforeEach(() => {
    h.triggerFull.mockClear()
    h.isSuper = false
  })

  it('非超管 → encrypt: false（拿明文包，服务端不会 403）', async () => {
    const w = mountView()
    await flushPromises()
    await (w.vm as unknown as BackupVm).triggerFull({ password: 'pw' })
    await flushPromises()

    expect(h.triggerFull).toHaveBeenCalledTimes(1)
    const first = h.triggerFull.mock.calls[0]
    expect(first).toBeDefined()
    expect(first?.[0].encrypt).toBe(false)
  })

  it('超管 → encrypt: true（拿完整加密包）', async () => {
    h.isSuper = true
    const w = mountView()
    await flushPromises()
    await (w.vm as unknown as BackupVm).triggerFull({ password: 'pw' })
    await flushPromises()

    expect(h.triggerFull).toHaveBeenCalledTimes(1)
    const second = h.triggerFull.mock.calls[0]
    expect(second).toBeDefined()
    expect(second?.[0].encrypt).toBe(true)
  })
})

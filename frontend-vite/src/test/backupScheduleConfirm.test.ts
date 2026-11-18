/**
 * 备份页「删除定时任务 / 立即触发」必须有二次确认（2026-10-17 审计 P1-18 / 报告内 FE-DESK-B P1-1）。
 *
 * 事故形态：`DELETE /backup/schedule/{id}` 是后端**硬删**（无软删、无回收站、无撤销），
 * 前端却把「删除」做成行内一个普通按钮：单击即生效，无确认、无撤销。被删的若是
 * 「每日全量备份」「备份巡检」「恢复演练」这类例行调度，系统会**静默失去自动备份能力**——
 * `getStatus()` 仍显示「上次备份成功」，直到某天发现备份缺位才暴露（窗口可能长达数周）。
 * 同页「删除备份文件」「上传还原」都走 `confirmDialog`，唯独这两个入口漏了。
 *
 * 「立即触发」同样要确认，且文案必须写出**将要触发的任务名**（原实现只传 `id`，
 * 成功 toast 才第一次说出任务名，事后告知）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  confirmMock: vi.fn(),
  deleteSchedule: vi.fn(async () => ({ success: true })),
  triggerSchedule: vi.fn(async () => ({ success: true })),
  listSchedules: vi.fn(),
  toastError: vi.fn(),
  toastInfo: vi.fn(),
  toastSuccess: vi.fn(),
}))

vi.mock('@/api', () => ({
  backupApi: {
    getStatus: vi.fn(async () => ({})),
    listSchedules: mocks.listSchedules,
    getSettings: vi.fn(async () => ({})),
    getRecords: vi.fn(async () => ({ records: [], total: 0 })),
    deleteSchedule: mocks.deleteSchedule,
    triggerSchedule: mocks.triggerSchedule,
  },
}))

vi.mock('@/composables/useToast', () => ({
  toast: {
    error: mocks.toastError,
    info: mocks.toastInfo,
    success: mocks.toastSuccess,
    warning: vi.fn(),
  },
}))

vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: false,
    text: '',
    sub: '',
    type: 'danger',
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    confirm: mocks.confirmMock,
  }),
}))

vi.mock('@/components/backup/composables/useBackupTask', () => ({
  useBackupTask: () => ({ state: ref(null) }),
}))

// 2026-11-18：BackupView 现在按登录用户的超管身份决定 triggerFull 的 encrypt
// 参数（加密包含现役私钥与 .env，服务端对非超管 403）。本测试只关心二次确认，
// 不装 Pinia —— 直接给出一个超管桩，保持它原有的可挂载性。
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { is_super: true } }),
}))

import BackupView from '@/views/backup/BackupView.vue'
import ScheduleConfig from '@/components/backup/ScheduleConfig.vue'

const SCHEDULES = [
  { id: 3, name: '每日全量备份', enabled: true, cron_expr: '0 2 * * *', schedule: '0 2 * * *' },
  { id: 4, name: '备份巡检', enabled: true, cron_expr: '0 5 * * *', schedule: '0 5 * * *' },
]

interface BackupVm {
  deleteSchedule: (id: number, name: string) => Promise<void>
  triggerScheduleNow: () => Promise<void>
}

function mountView() {
  return mount(BackupView, {
    global: {
      stubs: {
        BackupOverviewCards: true,
        BackupActions: true,
        ScheduleConfig: true,
        PathSettings: true,
        RestoreConfirmDialog: true,
        BackupRecordTable: true,
        UiConfirmDialog: true,
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.listSchedules.mockResolvedValue({ tasks: SCHEDULES })
  mocks.confirmMock.mockResolvedValue(false)
})

describe('P1-18 删除定时任务必须二次确认', () => {
  it('用户取消 → 不发删除请求，且确认文案写出任务名', async () => {
    const w = mountView()
    await flushPromises()
    const vm = w.vm as unknown as BackupVm

    await vm.deleteSchedule(3, '每日全量备份')
    await flushPromises()

    expect(mocks.confirmMock).toHaveBeenCalledTimes(1)
    const [text, sub, type] = mocks.confirmMock.mock.calls[0] ?? []
    expect(String(text)).toContain('每日全量备份')
    expect(String(sub)).toContain('无法恢复')
    expect(type).toBe('danger')
    // 关键断言：取消后绝不发 DELETE（原实现单击即删）
    expect(mocks.deleteSchedule).not.toHaveBeenCalled()
  })

  it('用户确认 → 才发删除请求并重新拉取列表', async () => {
    mocks.confirmMock.mockResolvedValue(true)
    const w = mountView()
    await flushPromises()
    const vm = w.vm as unknown as BackupVm
    mocks.listSchedules.mockClear()

    await vm.deleteSchedule(3, '每日全量备份')
    await flushPromises()

    expect(mocks.deleteSchedule).toHaveBeenCalledWith(3)
    expect(mocks.listSchedules).toHaveBeenCalled()
  })
})

describe('P1-18 立即触发定时任务必须二次确认', () => {
  it('用户取消 → 不入队，确认文案写出将要触发的任务名', async () => {
    const w = mountView()
    await flushPromises()
    const vm = w.vm as unknown as BackupVm

    await vm.triggerScheduleNow()
    await flushPromises()

    expect(mocks.confirmMock).toHaveBeenCalledTimes(1)
    const [text] = mocks.confirmMock.mock.calls[0] ?? []
    // 首个 enabled 调度是「每日全量备份」：文案必须点出它，不能只在成功 toast 里事后说明
    expect(String(text)).toContain('每日全量备份')
    expect(mocks.triggerSchedule).not.toHaveBeenCalled()
  })

  it('用户确认 → 触发首个已启用任务', async () => {
    mocks.confirmMock.mockResolvedValue(true)
    const w = mountView()
    await flushPromises()
    const vm = w.vm as unknown as BackupVm

    await vm.triggerScheduleNow()
    await flushPromises()

    expect(mocks.triggerSchedule).toHaveBeenCalledWith('每日全量备份')
  })

  it('没有已启用任务 → 不发确认、不入队，只提示', async () => {
    mocks.listSchedules.mockResolvedValue({
      tasks: [{ id: 9, name: '清理', enabled: false, schedule: '0 3 * * *' }],
    })
    const w = mountView()
    await flushPromises()
    const vm = w.vm as unknown as BackupVm

    await vm.triggerScheduleNow()
    await flushPromises()

    expect(mocks.confirmMock).not.toHaveBeenCalled()
    expect(mocks.triggerSchedule).not.toHaveBeenCalled()
    expect(mocks.toastInfo).toHaveBeenCalledWith('当前没有启用的定时任务')
  })
})

describe('ScheduleConfig 行内删除按钮', () => {
  it('删除时把任务名一并传给 onDelete（只传 id 无法给出可读确认文案）', async () => {
    const onDelete = vi.fn()
    const w = mount(ScheduleConfig, {
      props: { schedules: SCHEDULES, onSave: () => {}, onDelete, onTrigger: () => {} },
    })

    await w.findAll('.sc-item-del')[0]!.trigger('click')

    expect(onDelete).toHaveBeenCalledWith(3, '每日全量备份')
  })
})

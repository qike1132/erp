/**
 * AUD-10/11/12（2026-10-24 上线前审计）前端回归锁：
 * 1. useSamplingProject 三函数重入守卫——双击「创建」曾并发发出两个 createProject
 *    建出两个重复打样项目（按钮/hook/函数三层均无防护）；
 * 2. useApproval.handleApprove 失败后必须复位 actionId——原先该行按钮永久
 *    禁用显示「处理中…」直到刷新；
 * 3. DashboardMobile Hero 标签与数据一致——orders.total_qty 是全历史累计，
 *    原标签「本月订单」恒显示累计值（AUD-12）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const { createProjectMock } = vi.hoisted(() => ({
  createProjectMock: vi.fn(),
}))

vi.mock('@/api/patternRoom', () => ({
  patternRoomApi: {
    createProject: createProjectMock,
    updateProject: vi.fn(),
    deleteProject: vi.fn(),
  },
}))

import { useSamplingProject } from '../views/pattern-room/composables/useSamplingProject'

describe('AUD-10 useSamplingProject 重入守卫', () => {
  beforeEach(() => {
    createProjectMock.mockReset()
  })

  it('create 在途时再次调用直接返回 null，不发第二个请求', async () => {
    let release!: () => void
    createProjectMock.mockImplementation(
      () => new Promise((resolvePromise) => { release = () => resolvePromise({ id: 1 }) }),
    )
    const { create, submitting } = useSamplingProject()

    const first = create({} as never)
    const second = await create({} as never)

    expect(second).toBeNull()
    expect(createProjectMock).toHaveBeenCalledTimes(1)
    release()
    expect((await first)?.id).toBe(1)
    expect(submitting.value).toBe(false)
  })

  it('结束后守卫复位：下一次 create 正常发出', async () => {
    createProjectMock.mockResolvedValue({ id: 2 })
    const { create } = useSamplingProject()
    await create({} as never)
    await create({} as never)
    expect(createProjectMock).toHaveBeenCalledTimes(2)
  })
})

describe('AUD-11 useApproval.handleApprove 失败复位', () => {
  const { approveMock, invalidateMock } = vi.hoisted(() => ({
    approveMock: vi.fn(),
    invalidateMock: vi.fn(),
  }))

  vi.mock('@/api', () => ({
    approvalApi: { approve: approveMock },
  }))
  vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
  vi.mock('@/composables/useDebouncedSearch', () => ({
    useDebouncedSearch: () => ({ debounced: ref('') }),
  }))
  vi.mock('@tanstack/vue-query', () => ({
    useQuery: () => ({ data: ref([]), isFetching: ref(false) }),
    useQueryClient: () => ({ invalidateQueries: invalidateMock }),
  }))

  it('approve 抛错后 actionId 复位为 0（按钮不得永久卡「处理中…」）', async () => {
    approveMock.mockRejectedValue({ response: { data: { detail: '网络错误' } } })
    const { useApproval } = await import('../views/approval/composables/useApproval')
    const { handleApprove, actionId } = useApproval()
    await handleApprove({ id: 42 } as never)
    expect(actionId.value).toBe(0)
  })

  it('approve 成功路径同样复位', async () => {
    approveMock.mockResolvedValue({ success: true })
    const { useApproval } = await import('../views/approval/composables/useApproval')
    const { handleApprove, actionId } = useApproval()
    await handleApprove({ id: 43 } as never)
    expect(actionId.value).toBe(0)
  })
})

describe('AUD-12 移动端 Hero 标签与数据一致', () => {
  it('DashboardMobile 不再把累计值标成「本月订单」（模板行口径）', () => {
    const src = readFileSync(
      resolve(__dirname, '../mobile/views/dashboard/DashboardMobile.vue'), 'utf-8')
    // 只断言模板行（注释可提及历史标签名）；span 行必须用「累计订单」绑定 total_qty
    expect(/<span>本月订单/.test(src)).toBe(false)
    expect(/<span>累计订单 \{\{ fmtNum\(data\?\.orders\?\.total_qty\) \}\}<\/span>/.test(src)).toBe(true)
  })
})

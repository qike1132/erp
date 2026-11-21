import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ProjectDetailResponse } from '@/api/patternRoom'

// hoisted：保证 mock 变量先于 vi.mock 工厂初始化
const { uploadProjectImage } = vi.hoisted(() => ({ uploadProjectImage: vi.fn() }))

vi.mock('@/api/patternRoom', () => ({ patternRoomApi: { uploadProjectImage } }))

import { useSamplingProject } from '../views/pattern-room/composables/useSamplingProject'

/**
 * useSamplingProject.uploadImage 的乐观锁版本回写（审计 L-7）
 *
 * 服务端 upload.py 明确返回自增后的 `version`；旧实现用「本地 +1」回写，
 * 与并发 fetchDetail（其 version 已含上传自增）相遇时会双算，
 * 下一次保存必吃假 409。回写必须以响应里的服务端真相为准。
 */

function makeFile(): File {
  return new File([new Uint8Array([1, 2, 3])], 'a.png', { type: 'image/png' })
}

describe('useSamplingProject.uploadImage 版本回写', () => {
  beforeEach(() => {
    uploadProjectImage.mockReset()
  })

  it('回写响应返回的 version，而非本地 +1（详情并发已含自增时防双算）', async () => {
    const hook = useSamplingProject()
    hook.currentProject.value = { id: 7, version: 4 } as ProjectDetailResponse
    // 并发 fetchDetail 先落地：详情 version 已含上传自增（4 → 5）；随后上传响应回传 5
    uploadProjectImage.mockImplementation(async () => {
      if (hook.currentProject.value) hook.currentProject.value.version = 5
      return { success: true, file_id: 5, url: '/static/uploads/a.png', version: 5 }
    })

    await hook.uploadImage(7, makeFile())

    // 旧实现 (5 ?? 0) + 1 = 6；正确值 = 响应的 5
    expect(hook.currentProject.value!.version).toBe(5)
  })

  it('响应缺 version 时保持现值（写 undefined 会让后端跳过乐观锁校验）', async () => {
    const hook = useSamplingProject()
    hook.currentProject.value = { id: 7, version: 4 } as ProjectDetailResponse
    uploadProjectImage.mockResolvedValue({ success: true, url: '/static/uploads/a.png' })

    await hook.uploadImage(7, makeFile())

    expect(hook.currentProject.value!.version).toBe(4)
  })

  it('详情不属于该项目时不回写', async () => {
    const hook = useSamplingProject()
    hook.currentProject.value = { id: 99, version: 4 } as ProjectDetailResponse
    uploadProjectImage.mockResolvedValue({ success: true, url: '/u.png', version: 5 })

    await hook.uploadImage(7, makeFile())

    expect(hook.currentProject.value!.version).toBe(4)
  })
})

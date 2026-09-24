import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import type { ProjectStatus, ProjectUpdateRequest } from '../api/patternRoom'

// hoisted：保证 mock 变量先于 vi.mock 工厂初始化
const { showToast, uploadProjectImage } = vi.hoisted(() => ({
  showToast: vi.fn((_message: string, _type?: string) => undefined),
  uploadProjectImage: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({ showToast }))
vi.mock('@/api/patternRoom', () => ({ patternRoomApi: { uploadProjectImage } }))

import { usePatternRoomProjectActions } from '../views/pattern-room/composables/usePatternRoomProjectActions'

function makeFile(name = 'pasted.png'): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: 'image/png' })
}

/** 以最小桩对象驱动 CRUD 编排 Hook，只关心后台图片上传的反馈分支 */
function buildActions() {
  const currentProject = ref({
    id: 7,
    product_image_url: '',
    product_image_thumbnail_url: null,
    product_image_file_id: null,
  })
  const projectHook = {
    currentProject,
    submitting: ref(false),
    create: vi.fn(async () => ({ id: 7 })),
    update: vi.fn(async () => ({ success: true })),
    fetchDetail: vi.fn(async () => currentProject.value),
    remove: vi.fn(async () => ({ success: true })),
  }
  const groupHook = {
    currentPage: ref(1),
    loadGrouped: vi.fn(async () => undefined),
  }
  const options = {
    canManage: ref(true),
    confirmDialog: { confirm: vi.fn(async () => true) },
    groupHook,
    projectHook,
    selectedProjectId: ref<number | null>(7),
    searchKeyword: ref(''),
    statusFilter: ref<ProjectStatus>('in_progress'),
    isNarrow: ref(false),
    drawerOpen: ref(false),
    formPatternMakerId: ref<number | null>(null),
    onSelectProject: vi.fn(),
  }
  const actions = usePatternRoomProjectActions(
    options as unknown as Parameters<typeof usePatternRoomProjectActions>[0],
  )
  return { actions, currentProject }
}

/** 触发一次「保存编辑 → 后台图片上传」链路 */
async function submitWithPendingImage(actions: ReturnType<typeof buildActions>['actions']) {
  actions.onProjectUploadImage(makeFile())
  const payload = { product_name: '小熊毛绒玩具', remark: '', version: 1 } as ProjectUpdateRequest
  await actions.onProjectSubmitUpdate(payload)
}

describe('打样项目图片后台上传的反馈', () => {
  beforeEach(() => {
    showToast.mockClear()
    uploadProjectImage.mockReset()
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('后台上传成功：success toast 且本地打补丁为新地址', async () => {
    uploadProjectImage.mockResolvedValue({
      success: true,
      url: '/static/uploads/a.png',
      thumbnail_url: '/static/uploads/a_thumb.png',
      file_id: 5,
    })
    const { actions, currentProject } = buildActions()

    await submitWithPendingImage(actions)

    expect(uploadProjectImage).toHaveBeenCalledTimes(1)
    await vi.waitFor(() => {
      expect(showToast).toHaveBeenCalledWith('图片上传成功', 'success')
    })
    expect(currentProject.value.product_image_url).toBe('/static/uploads/a.png')
  })

  it('后台上传失败：error toast 提示重试', async () => {
    uploadProjectImage.mockRejectedValue(new Error('network down'))
    const { actions } = buildActions()

    await submitWithPendingImage(actions)

    await vi.waitFor(() => {
      expect(showToast).toHaveBeenCalledWith('图片上传失败，请重试', 'error')
    })
  })
})

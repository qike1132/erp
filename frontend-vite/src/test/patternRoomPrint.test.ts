import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import PrintDialog from '@/views/pattern-room/components/PrintDialog.vue'
// 样式断言需要源码文本：jsdom 不实现 object-fit 的计算样式
import printDialogSource from '@/views/pattern-room/components/PrintDialog.vue?raw'
import type { PartDetail, ProjectDetailResponse, RoleBrief } from '@/api/patternRoom'

/**
 * 打样单打印回归测试（PrintDialog 渲染 + usePatternRoomPrint 取数）
 *
 * 背景：角色分段原先由「部位数据」反推、且强制按 role.current_version 过滤，导致
 * 1) 最终版本无数据的角色（current_version 指向空版本/已不存在的版本）整段消失；
 * 2) 尚未录入部位的角色整段消失。
 * 两者在打印预览里都表现为「角色信息遗漏」。
 */

const { getPartsByVersion } = vi.hoisted(() => ({ getPartsByVersion: vi.fn() }))

vi.mock('@/api/patternRoom', () => ({ patternRoomApi: { getPartsByVersion } }))

import { usePatternRoomPrint } from '@/views/pattern-room/composables/usePatternRoomPrint'

function makeRole(id: number, roleName: string, currentVersion = 'T1'): RoleBrief {
  return {
    id,
    project_id: 5029,
    role_name: roleName,
    sort_order: id,
    is_default: id === 1,
    current_version: currentVersion,
    created_at: '2026-09-24T00:00:00',
    updated_at: '2026-09-24T00:00:00',
    version: 1,
  }
}

let partSeq = 0

function makePart(roleId: number | null, partName: string, versionNo = 'T1'): PartDetail {
  partSeq += 1
  return {
    id: partSeq,
    project_id: 5029,
    role_id: roleId,
    part_name: partName,
    sort_order: partSeq,
    fabric_name: '赛乐绒',
    fabric_spec: '',
    fabric_color_no: '89',
    supplier_id: null,
    supplier_name: '伟昇',
    contact_person: '',
    contact_phone: '',
    unit_price: null,
    delivery_days: null,
    remark: '',
    version: 1,
    version_no: versionNo,
  }
}

const PROJECT = {
  id: 5029,
  product_name: '童话蛋仔',
  product_image_url: '/static/uploads/a.png',
  pattern_maker_name: '陈姐',
  updated_at: '2026-09-24T04:13:00',
} as unknown as ProjectDetailResponse

// ==================== PrintDialog 渲染 ====================

let wrapper: VueWrapper | null = null

function mountSheet(roles: RoleBrief[], parts: PartDetail[]) {
  wrapper = mount(PrintDialog, { props: { project: PROJECT, parts, roles }, attachTo: document.body })
  return wrapper
}

/** 组件通过 Teleport 渲染到 body，断言需直接查询 document */
function roleTitles(): string[] {
  return [...document.querySelectorAll('.pd-role-title')].map((el) => el.textContent?.trim() ?? '')
}

function rowsOfRole(index: number): string[] {
  const section = document.querySelectorAll('.pd-role-section')[index]
  if (!section) throw new Error(`角色分段缺失: index=${index}`)
  return [...section.querySelectorAll('tbody tr')].map((tr) =>
    (tr.textContent ?? '').replace(/\s+/g, ' ').trim(),
  )
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('PrintDialog 角色分段（打样单不遗漏角色）', () => {
  it('无部位数据的角色同样输出分段并提示「暂无部位数据」', () => {
    mountSheet(
      [makeRole(1, '默认'), makeRole(2, '黄蛋'), makeRole(3, '粉蛋')],
      [makePart(2, '主料'), makePart(2, '肤色'), makePart(3, '主料')],
    )

    expect(roleTitles()).toEqual(['默认', '黄蛋', '粉蛋'])
    expect(rowsOfRole(0)).toEqual(['暂无部位数据'])
    expect(rowsOfRole(1)).toHaveLength(2)
  })

  it('角色列表外的 role_id 追加到末尾，数据不被丢弃', () => {
    mountSheet([makeRole(1, '默认')], [makePart(99, '主料')])

    expect(roleTitles()).toEqual(['默认', '角色99'])
  })

  it('同一角色下同名部位只输出一行', () => {
    mountSheet([makeRole(2, '黄蛋')], [makePart(2, '主料'), makePart(2, '主料')])

    expect(rowsOfRole(0)).toHaveLength(1)
  })

  it('分段顺序跟随角色列表顺序', () => {
    mountSheet(
      [makeRole(3, '粉蛋'), makeRole(1, '默认'), makeRole(2, '黄蛋')],
      [makePart(1, '主料'), makePart(3, '主料')],
    )

    expect(roleTitles()).toEqual(['粉蛋', '默认', '黄蛋'])
  })
})

describe('PrintDialog 产品图片完整性', () => {
  it('打印图片使用 contain，保证整张图片可见（cover 会裁剪非正方形图片）', () => {
    const imageRule = printDialogSource.match(/\.pd-image \{[\s\S]*?\}/)?.[0] ?? ''

    expect(imageRule).toContain('object-fit: contain')
    expect(imageRule).not.toContain('object-fit: cover')
  })
})

// ==================== usePatternRoomPrint 取数 ====================

describe('usePatternRoomPrint 取数（最终版本无数据时回退）', () => {
  beforeEach(() => {
    getPartsByVersion.mockReset()
    vi.spyOn(window, 'print').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('最终版本无数据的角色回退取「最新且有数据」的版本，角色不被整段漏打', async () => {
    getPartsByVersion.mockImplementation(
      async (_projectId: number, roleId?: number, finalOnly?: boolean) => {
        // 黄蛋：current_version=T2，但 T2 下无任何部位（部位仍停留在 T1）
        if (roleId === 4104 && finalOnly) {
          return { success: true, items: [], versions: [], final_version: 'T2' }
        }
        if (roleId === 4104) {
          return {
            success: true,
            items: [makePart(4104, '主料', 'T1'), makePart(4104, '肤色', 'T1')],
            versions: ['T1'],
            final_version: 'T2',
          }
        }
        if (roleId === 4105) {
          return {
            success: true,
            items: [makePart(4105, '主料', 'T1')],
            versions: ['T1'],
            final_version: 'T1',
          }
        }
        // 默认角色：完全没有部位数据
        return { success: true, items: [], versions: [], final_version: 'T1' }
      },
    )

    const roles = ref([makeRole(4103, '默认'), makeRole(4104, '黄蛋', 'T2'), makeRole(4105, '粉蛋')])
    const selectedProjectId = ref<number | null>(5029)
    const partsByVersion = ref([makePart(4105, '主料', 'T1')])

    const api = effectScope().run(() =>
      usePatternRoomPrint({ selectedProjectId, partsByVersion, roles }),
    )!

    await api.handlePrint()

    // 所有角色都进入打印数据（无部位数据的角色由 PrintDialog 输出空分段）
    expect(api.printRoles.value.map((r) => r.role_name)).toEqual(['默认', '黄蛋', '粉蛋'])
    // 黄蛋的 T1 部位被找回，不再整段消失
    expect(api.printParts.value.map((p) => `${p.role_id}:${p.part_name}@${p.version_no}`)).toEqual([
      '4104:主料@T1',
      '4104:肤色@T1',
      '4105:主料@T1',
    ])
    // 只对「最终版本无数据」的角色发起回退请求
    const fallbackCalls = getPartsByVersion.mock.calls.filter((c) => c[2] === undefined)
    expect(fallbackCalls.map((c) => c[1])).toEqual([4103, 4104])
  })

  it('未知版本号（versions 为空）时回退保留全部行，避免空白', async () => {
    getPartsByVersion.mockImplementation(
      async (_projectId: number, roleId?: number, finalOnly?: boolean) => {
        if (finalOnly) return { success: true, items: [], versions: [], final_version: 'T9' }
        return {
          success: true,
          items: [makePart(roleId!, '主料', '')],
          versions: [],
          final_version: 'T9',
        }
      },
    )

    const roles = ref([makeRole(1, '默认', 'T9')])
    const api = effectScope().run(() =>
      usePatternRoomPrint({
        selectedProjectId: ref<number | null>(5029),
        partsByVersion: ref([makePart(1, '主料', '')]),
        roles,
      }),
    )!

    await api.handlePrint()

    expect(api.printParts.value).toHaveLength(1)
  })
})

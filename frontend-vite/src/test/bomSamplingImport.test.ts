import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import type { PartDetail, ProjectSummary, RoleBrief } from '@/api/patternRoom'
import {
  buildSamplingImportRows,
  buildSamplingRemark,
  mapSamplingPartToBom,
} from '@/views/product/composables/bomSamplingImport'
import type { BomItem, Role } from '@/views/product/composables/bomTypes'

const mocks = vi.hoisted(() => ({
  loadBom: vi.fn(),
  saveBom: vi.fn(),
  listProjects: vi.fn(),
  listRoles: vi.fn(),
  getPartsByVersion: vi.fn(),
}))

vi.mock('@/api', () => ({
  productApi: {
    loadBom: mocks.loadBom,
    saveBom: mocks.saveBom,
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    searchForBomCopy: vi.fn(),
  },
  supplierApi: { options: vi.fn().mockResolvedValue({ suppliers: [{ id: 9, name: '供应商甲' }] }) },
}))

vi.mock('@/api/patternRoom', () => ({
  patternRoomApi: {
    listProjects: mocks.listProjects,
    listRoles: mocks.listRoles,
    getPartsByVersion: mocks.getPartsByVersion,
  },
}))

import BomEditor from '@/views/product/components/BomEditor.vue'

function part(id: number, partName: string, overrides: Partial<PartDetail> = {}): PartDetail {
  return {
    id,
    part_name: partName,
    fabric_name: `${partName}布料`,
    fabric_spec: `${partName}规格`,
    fabric_color_no: `C-${id}`,
    supplier_id: 9,
    supplier_name: '供应商甲',
    remark: '原备注',
    ...overrides,
  } as PartDetail
}

function role(id: number, roleName: string): RoleBrief {
  return {
    id, project_id: 11, role_name: roleName, current_version: 'T2', sort_order: id,
    is_default: false, created_at: '2026-11-07', updated_at: '2026-11-07', version: 1,
  }
}

function project(id: number, sequenceNo: string): ProjectSummary {
  return {
    id,
    sequence_no: sequenceNo,
    product_name: '测试产品',
    status: 'in_progress',
    current_version: 'T2',
    product_image_url: null,
    product_image_thumbnail_url: null,
    product_image_blur_url: null,
    completed_at: null,
    parts_count: 2,
    updated_at: '2026-11-07',
  }
}

describe('打样单导入纯映射', () => {
  it('色号进入规格型号且不拼进备注，数量默认为 0；供应商 id 无效时留空', () => {
    const source = part(1, '身体', { fabric_color_no: '红-01', remark: ' keep ', supplier_id: 999 })
    const mapped = mapSamplingPartToBom(source, new Set([9]))

    expect(buildSamplingRemark(source)).toBe('keep')
    expect(mapped).toMatchObject({
      part_name: '身体',
      name: '身体布料',
      specification: '红-01',
      supplier_id: null,
      supplier_name: '供应商甲',
      usage: 0,
      quantity_pending: true,
      unit: '码',
      remark: 'keep',
    })
  })

  it('色号为空时才回退使用 fabric_spec 作为规格型号', () => {
    const source = part(2, '领口', { fabric_color_no: '', fabric_spec: '32 支', remark: '原备注' })
    expect(mapSamplingPartToBom(source, new Set([9]))).toMatchObject({
      specification: '32 支',
      remark: '原备注',
    })
  })

  it('跨角色同名部位标冲突；目标角色已有同部位标覆盖，否则新增', () => {
    const roles: Role[] = [{ id: 7, name: '客户A' }]
    const groups = [
      { role: role(100, '客户A'), parts: [part(1, '身体'), part(2, '领口')] },
      { role: role(101, '客户B'), parts: [part(3, '身体')] },
    ]
    const targetItems: BomItem[] = [{
      id: 8, part_name: '领口', name: '旧', specification: '旧', unit: '码',
      supplier_name: '旧', usage: 2, remark: '', role_id: 7,
    }]
    const rows = buildSamplingImportRows(groups, roles, () => targetItems)

    expect(rows.map((row) => row.status)).toEqual(['conflict', 'overwrite', 'conflict'])
    expect(rows.every((row) => row.selected && row.quantityPending)).toBe(true)
  })

})

interface ExposedEditor {
  open: (product: { id: number; name: string }) => Promise<void>
}

let wrapper: VueWrapper | null = null

function q(selector: string): DOMWrapper<Element> {
  const element = document.querySelector(selector)
  if (!element) throw new Error(`未找到 ${selector}`)
  return new DOMWrapper(element)
}

function qa(selector: string): DOMWrapper<Element>[] {
  return [...document.querySelectorAll(selector)].map((element) => new DOMWrapper(element))
}

async function openEditor() {
  wrapper = mount(BomEditor, {
    attachTo: document.body,
    global: { stubs: { UiAutocomplete: true, BomCopyDialog: true, BomSupplierSelect: true } },
  })
  await (wrapper.vm as unknown as ExposedEditor).open({ id: 1, name: '测试产品' })
  await flushPromises()
  await nextTick()
  return wrapper
}

describe('BomEditor 从打样单导入完整链路', () => {
  beforeEach(() => {
    mocks.loadBom.mockResolvedValue({
      success: true,
      product: { roles: [{ id: 7, name: '客户A' }], default_bom_label: null },
      materials: [{
        id: 8, category: 'fabric', part_name: '领口', material_name: '旧布料', specification: '旧规格',
        unit: '码', supplier_id: 9, supplier_name: '供应商甲', unit_usage: 2, remark: '旧备注', role_id: 7,
      }],
    })
    mocks.saveBom.mockResolvedValue({ success: true })
    mocks.listProjects.mockResolvedValue({ success: true, items: [project(11, 'DY-001'), project(12, 'DY-002')], total: 2 })
    mocks.listRoles.mockImplementation(async (projectId: number) => ({
      success: true,
      items: projectId === 11 ? [role(100, '客户A'), role(101, '客户B')] : [role(200, '客户C')],
    }))
    mocks.getPartsByVersion.mockImplementation(async (_projectId: number, roleId: number) => ({
      success: true,
      items: roleId === 100
        ? [part(1, '领口'), part(2, '身体')]
        : [part(3, '身体', { supplier_id: 999 }), part(4, '袖子', {
            unit_price: 12.5, delivery_days: 7, contact_person: '张三', contact_phone: '13800000000',
          })],
    }))
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    document.body.innerHTML = ''
    vi.clearAllMocks()
  })

  it('列出同名打样单，复用 final_only，冲突/映射/角色/保存回显均正确', async () => {
    const w = await openEditor()
    if (!document.querySelector('.bom-btn-import-v2')) throw new Error(`BOM 弹窗未渲染：${document.body.innerHTML.slice(0, 1200)}`)
    await q('.bom-btn-import-v2').trigger('click')
    expect((q('#sampling-product-keyword').element as HTMLInputElement).value).toBe('测试产品')
    await q('.sampling-search-line button').trigger('click')
    await flushPromises()
    await nextTick()

    expect(mocks.listProjects).toHaveBeenCalledWith({ keyword: '测试产品', status: 'all', page: 1, per_page: 100 })
    expect(qa('.sampling-project-table tbody tr')).toHaveLength(2)
    expect(q('.sampling-project-table').text()).toContain('DY-001')
    expect(q('.sampling-project-table').text()).toContain('DY-002')

    await qa('.sampling-project-table tbody tr')[0]!.find('button').trigger('click')
    await flushPromises()
    await nextTick()
    expect(mocks.getPartsByVersion).toHaveBeenCalledWith(11, 100, true)
    expect(mocks.getPartsByVersion).toHaveBeenCalledWith(11, 101, true)
    expect(qa('.sampling-row-conflict')).toHaveLength(2)
    expect(qa('.sampling-row-overwrite')).toHaveLength(1)
    expect(qa('.sampling-row-new')).toHaveLength(1)
    expect(q('.sampling-preview').text()).toContain('以下字段未导入：单价、交期、联系人、联系电话')
    expect(q('.sampling-preview').text()).toContain('单价：12.5')
    expect(q('.sampling-preview').text()).toContain('联系人：张三')

    await q('.sampling-confirm').trigger('click')
    await flushPromises()
    await nextTick()
    expect(mocks.saveBom).not.toHaveBeenCalled()
    expect(qa('.bom-role-tab').map((tab) => tab.text().trim())).toEqual(['客户A', '客户B'])
    expect(qa('.bom-table-v2 tbody tr')).toHaveLength(2)
    expect(qa('.bom-quantity-pending-label')).toHaveLength(2)
    expect(q('.bom-table-v2').text()).toContain('数量待补')
    const quantityInputs = qa('.bom-table-v2 input[name="quantity"]')
    expect(quantityInputs.every((input) => (input.element as HTMLInputElement).value === '0')).toBe(true)
    // 用户缺陷定向断言：不经过保存，导入后「规格型号 *」与「备注」两个
    // 原生输入框必须各自绑定正确字段，不能借保存 payload 掩盖表格列错位。
    const immediateSpecs = qa('.bom-table-v2 input[name="specification"]').map((input) => (input.element as HTMLInputElement).value)
    const immediateRemarks = qa('.bom-table-v2 input[name="remark"]').map((input) => (input.element as HTMLInputElement).value)
    expect(immediateSpecs).toEqual(['C-1', 'C-2'])
    expect(immediateRemarks).toEqual(['原备注', '原备注'])

    await q('.bom-btn-save').trigger('click')
    await flushPromises()
    expect(mocks.saveBom).toHaveBeenCalledTimes(1)
    const payload = mocks.saveBom.mock.calls[0]![1] as {
      roles: Array<Record<string, unknown>>
      fabrics: Array<Record<string, unknown>>
    }
    expect(payload.roles).toEqual([{ id: 7, role_name: '客户A' }, { role_key: 'rk-1', role_name: '客户B' }])
    const bodyA = payload.fabrics.find((item) => item.part_name === '身体' && item.role_id === 7)!
    expect(bodyA).toMatchObject({ fabric_name: '身体布料', specification: 'C-2', quantity: 0, remark: '原备注', supplier_id: 9 })
    const bodyB = payload.fabrics.find((item) => item.part_name === '身体' && item.role_key === 'rk-1')!
    expect(bodyB).toMatchObject({ specification: 'C-3', supplier_id: null, quantity: 0, remark: '原备注' })
    expect(payload.fabrics.find((item) => item.part_name === '领口')).toMatchObject({ id: 8, role_id: 7, quantity: 0 })

    // 模拟既有保存端点提交成功后重新读取，验证回显字段及 role 归属不漂移。
    mocks.loadBom.mockResolvedValue({
      success: true,
      product: { roles: [{ id: 7, name: '客户A' }, { id: 77, name: '客户B' }], default_bom_label: null },
      materials: payload.fabrics.map((item, index) => ({
        id: typeof item.id === 'number' ? item.id : 100 + index,
        category: 'fabric', part_name: item.part_name, material_name: item.fabric_name,
        specification: item.specification, unit: item.unit, quantity: item.quantity,
        supplier_id: item.supplier_id, supplier_name: item.supplier_name, remark: item.remark,
        role_id: item.role_id === 7 ? 7 : 77,
      })),
    })
    await (w.vm as unknown as ExposedEditor).open({ id: 1, name: '测试产品' })
    await flushPromises()
    await nextTick()
    await qa('.bom-role-tab')[1]!.trigger('click')
    await nextTick()
    const reopenedParts = qa('.bom-table-v2 input[name="part-name"]').map((input) => (input.element as HTMLInputElement).value)
    const reopenedNames = qa('.bom-table-v2 input[name="material-name"]').map((input) => (input.element as HTMLInputElement).value)
    const reopenedSpecs = qa('.bom-table-v2 input[name="specification"]').map((input) => (input.element as HTMLInputElement).value)
    expect(reopenedParts).toEqual(['身体', '袖子'])
    expect(reopenedNames).toEqual(['身体布料', '袖子布料'])
    expect(reopenedSpecs).toEqual(['C-3', 'C-4'])
    const remarks = qa('.bom-table-v2 input[name="remark"]').map((input) => (input.element as HTMLInputElement).value)
    expect(remarks).toEqual(['原备注', '原备注'])
  })

  it('保存后重新打开角色-only BOM：默认作用域为空时自动显示有数据的角色', async () => {
    mocks.loadBom.mockResolvedValue({
      success: true,
      product: { roles: [{ id: 6, name: '默认' }], default_bom_label: null },
      materials: [
        { id: 541, category: 'fabric', part_name: '主体', material_name: '1.0超', specification: '1203#', unit: '码', supplier_id: 9, supplier_name: '美利达', quantity: 0.01, remark: '', role_id: 6 },
        { id: 542, category: 'fabric', part_name: '羊角', material_name: '1.0超', specification: 'A232#', unit: '码', supplier_id: 9, supplier_name: '美利达', quantity: 0.01, remark: '', role_id: 6 },
        { id: 543, category: 'fabric', part_name: '内耳', material_name: '1.0超', specification: 'A175#', unit: '码', supplier_id: 9, supplier_name: '美利达', quantity: 0.01, remark: '', role_id: 6 },
      ],
    })
    await openEditor()

    expect(q('.bom-role-tab.active').text()).toContain('默认')
    expect(qa('.bom-table-v2 tbody tr')).toHaveLength(3)
    expect(qa('.bom-table-v2 input[name="specification"]').map((input) => (input.element as HTMLInputElement).value)).toEqual(['1203#', 'A232#', 'A175#'])
  })

  it('403 在弹窗内给出打样单读权限提示，不是静默失败', async () => {
    mocks.listProjects.mockRejectedValue({ response: { status: 403 } })
    await openEditor()
    await q('.bom-btn-import-v2').trigger('click')
    await q('.sampling-search-line button').trigger('click')
    await flushPromises()
    await nextTick()

    expect(q('[role="alert"]').text()).toContain('customer_sampling_view')
    expect(q('[role="alert"]').text()).toContain('customer_sampling_manage')
  })
})

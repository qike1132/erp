/**
 * 工厂内部订单「角色名称」列（2026-11-08）。
 *
 * 需求：一个产品名称下有多个角色时，表格要能看出每行物料属于哪个角色。
 * 角色归属由后端按 BOM 的 role_id 产出（`role_display`），本测试锁定：
 *   R1 屏幕表头「角色名称」在「产品部位」之前（列序：客户/产品/订单/备品/角色/部位/供应商…）；
 *   R2 屏幕数据行把 `role_display` 渲染在角色格，且不污染部位格；
 *   R3 打印/导出与屏幕同序（FACTORY_TABLE_HEAD 与 buildFactoryHtml 同源）；
 *   R4 多角色共用同一物料时并列展示（`角色A/角色B`）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'
import {
  FACTORY_TABLE_HEAD,
  buildFactoryHtml,
} from '@/views/purchase/composables/useSummaryModal'
import type { FactoryGroup, FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

/** 一个产品名、两个角色：角色A 用「红布」、角色B 用「蓝布」，另有共用「松紧带」。 */
function roleGroup(): FactoryGroup {
  return {
    customer_name: '客户甲',
    product_name: '陈列样盲盒',
    product_quantity: 100,
    skus: [
      {
        product_name: '陈列样盲盒',
        product_barcode: 'B-1',
        order_qty: 100,
        materials: [
          {
            supplier_name: '供应商甲', material_name: '红布', part_name: '',
            part_display: '身体', role_display: '角色A',
            specification: 'S1', unit: '米', quantity: 10,
          },
          {
            supplier_name: '供应商甲', material_name: '蓝布', part_name: '',
            part_display: '头部', role_display: '角色B',
            specification: 'S2', unit: '米', quantity: 20,
          },
          {
            supplier_name: '供应商甲', material_name: '松紧带', part_name: '',
            part_display: '身体', role_display: '角色A/角色B',
            specification: 'S3', unit: '米', quantity: 5,
          },
        ],
      },
    ],
    suppliers: [
      {
        supplier_name: '供应商甲',
        fabrics: [
          { fabric_name: '红布', part_display: '身体', role_display: '角色A', specification: 'S1', unit: '米', quantity: 10, item_ids: [1] },
          { fabric_name: '蓝布', part_display: '头部', role_display: '角色B', specification: 'S2', unit: '米', quantity: 20, item_ids: [2] },
          { fabric_name: '松紧带', part_display: '身体', role_display: '角色A/角色B', specification: 'S3', unit: '米', quantity: 5, item_ids: [3] },
        ],
      },
    ],
  }
}

function dataOf(group: FactoryGroup): FactorySummaryData {
  return { success: true, order_count: 1, spare_rate: 0, groups: [group] }
}

function mountModal(group: FactoryGroup) {
  return mount(SummaryPanel, {
    props: {
      factoryData: dataOf(group),
      supplierData: { success: true, order_count: 1, materials: [] },
      editMode: false,
      lossRate: 0,
      orderCount: 1,
      supplierGroups: [],
    },
    attachTo: document.body,
  })
}

describe('工厂内部订单 · 角色名称列', () => {
  it('R1 屏幕表头「角色名称」紧跟「备品数量」，且在「产品部位」之前', () => {
    const wrapper = mountModal(roleGroup())
    const headers = wrapper.findAll('thead th').map((th) => th.text())
    expect(headers).toEqual([
      '客户', '产品名称', '订单数量', '备品数量', '角色名称', '产品部位', '供应商',
      '布料名称', '规格型号', '损耗率', '数量', '单位',
    ])
    wrapper.unmount()
  })

  it('R2 数据行逐行渲染各自角色名（含并列），部位列不被角色污染', () => {
    const wrapper = mountModal(roleGroup())
    // 只取工厂页签主表的数据行（`.smf-scroll` 是工厂表的滚动容器；排除对照块/其它页签）
    const rows = wrapper.findAll('.smf-scroll tbody tr').filter(
      (tr) => ['红布', '蓝布', '松紧带'].some((name) => tr.text().includes(name)),
    )
    expect(rows).toHaveLength(3)

    const cells = (i: number) => rows[i]!.findAll('td').map((td) => td.text())
    // 首行：客户/产品/订单/备品 4 格 + 角色 + 部位 + 供应商(rowspan) + 布料/规格/损耗率/数量/单位
    expect(cells(0).slice(4, 7)).toEqual(['角色A', '身体', '供应商甲'])
    // 第 2、3 行：供应商被 rowspan 覆盖 → 角色 + 部位 + 后 5 格
    expect(cells(1).slice(0, 2)).toEqual(['角色B', '头部'])
    expect(cells(2).slice(0, 2)).toEqual(['角色A/角色B', '身体'])
    wrapper.unmount()
  })

  it('R3 打印/导出表头与屏幕同序（共享常量含角色名称）', () => {
    expect(FACTORY_TABLE_HEAD).toContain('<th>角色名称</th><th>产品部位</th><th>供应商</th>')
  })

  it('R4 打印数据行把角色名渲染在部位格之前', () => {
    const html = buildFactoryHtml(dataOf(roleGroup()), 0)
    const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
    const first = [...doc.querySelectorAll('tbody tr:first-child td')].map((td) => td.textContent || '')
    expect(first[4]).toBe('角色A')
    expect(first[5]).toBe('身体')
    expect(first[6]).toBe('供应商甲')
    expect(html).toContain('角色A/角色B')
  })
})

/**
 * 「记录查询 → 物料清单」数量列回归测试。
 *
 * 两条契约：
 *   C1 「数量」列展示的是**最终采购数量**——按落库损耗率（千分之几）加放后向上取整，
 *      与「汇总下单 → 工厂内部采购订单汇总」的数量列同源同口径；
 *      回退链：逐行 loss_rate → 订单级 spare_rate → 0（旧数据 = 原始数量，零回归）。
 *   C2 「数量」列表头与数据统一居中——`.odm-table thead th` 的 text-align:left
 *      特异性高于 `.odm-th-num`，必须以更高特异性显式声明，否则表头左对齐、与数据错位。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import OrderDetailModal from '@/views/purchase/components/OrderDetailModal.vue'
// 源码级断言（样式归属）：用 Vite 的 ?raw 读原文，避免依赖 node:fs 类型
import OrderDetailModalSource from '@/views/purchase/components/OrderDetailModal.vue?raw'
import type { PurchaseOrder } from '@/types'

const stubs = {
  UiDialog: { template: '<div class="ui-dialog-stub"><slot name="footer" /><slot /></div>' },
}

function mountModal(order: PurchaseOrder) {
  return mount(OrderDetailModal, { props: { open: true, order }, global: { stubs } })
}

/** 取物料清单数据行（跳过表头行） */
function qtyCells(wrapper: ReturnType<typeof mountModal>): string[] {
  return wrapper.findAll('tbody tr td.odm-td-num').map((td) => td.text())
}

const baseOrder: PurchaseOrder = {
  id: 20447,
  order_no: 'CG-20260927-0012',
  status: 'completed',
  customer_name: 'MINISO国内',
  supplier_name: '—',
  create_time: '2026-09-27 07:31',
  order_date: '2026-09-27',
  spare_rate: 10,
  items: [
    { id: 1, material_name: '蓝色超柔', specification: '223', quantity: 890, unit: '码', loss_rate: 1000 },
    { id: 2, material_name: '漂白超柔', specification: '2', quantity: 920, unit: '码', loss_rate: 15 },
    { id: 3, material_name: '绿色超柔', specification: '234', quantity: 50, unit: '码', loss_rate: null },
    { id: 4, material_name: '木棒按摩锤', specification: '1条', quantity: 10000, unit: '个', loss_rate: 5 },
  ],
  sku_items: [],
}

describe('OrderDetailModal 物料清单「数量」列', () => {
  it('按逐行损耗率加放并向上取整（与汇总下单数量列同源）', () => {
    const w = mountModal(baseOrder)
    // 890 × (1 + 1000‰) = 1780
    // 920 × (1 + 15‰)   = 933.8  → 934
    // 50  × (1 + 10‰，回退订单级 spare_rate) = 50.5 → 51
    // 10000 × (1 + 5‰)  = 10050
    expect(qtyCells(w)).toEqual(['1,780', '934', '51', '10,050'])
  })

  it('订单级 spare_rate 缺失时回退 0：展示原始落库数量（旧数据零回归）', () => {
    const w = mountModal({
      ...baseOrder,
      spare_rate: null,
      items: [{ id: 1, material_name: '蓝色超柔', specification: '223', quantity: 890, unit: '码', loss_rate: null }],
    })
    expect(qtyCells(w)).toEqual(['890'])
  })

  it('损耗率为 0 时等于原始数量（不放行「假加放」）', () => {
    const w = mountModal({
      ...baseOrder,
      spare_rate: 0,
      items: [{ id: 1, material_name: '蓝色超柔', specification: '223', quantity: 890, unit: '码', loss_rate: 0 }],
    })
    expect(qtyCells(w)).toEqual(['890'])
  })

  it('数量列的表头与数据单元格都显式居中（压过 thead th 的 left）', () => {
    const rule = OrderDetailModalSource.match(
      /\.odm-table thead th\.odm-th-num,\s*\.odm-table tbody td\.odm-td-num \{([^}]*)\}/,
    )
    expect(rule, '数量列需要一条同时命中表头与单元格的高特异性居中规则').not.toBeNull()
    expect(rule![1]).toMatch(/text-align:\s*center/)
    expect(OrderDetailModalSource).not.toMatch(/\.odm-td-num \{[^}]*text-align:\s*right/)
  })
})

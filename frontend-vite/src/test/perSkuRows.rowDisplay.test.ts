/**
 * 数量展示唯一口径（buildRowDisplayQuantities）单元测试。
 *
 * 锁定：
 *  - 落库 ≠ ΣBOM → 以落库为权威（2026-11-10 的 207/52 收敛为 52）；
 *  - 非手工 → 逐 SKU BOM 推算（与改造前逐字一致）；
 *  - 多 SKU 共用 → 按 BOM 基准量权重做整数分摊，Σ各 SKU 行 ≡ 落库加放总量；
 *  - 无落库坐标 → 不加放。
 */
import { describe, it, expect } from 'vitest'
import { buildPerSkuRows, buildRowDisplayQuantities } from '@/views/purchase/composables/perSkuRows'
import type { FactoryGroup } from '@/views/purchase/composables/useSummaryModal'

type Mat = {
  supplier_name: string; material_name: string; specification: string; unit: string;
  quantity: number; part_name?: string; part_display?: string; role_id?: number | null
}

function group(opts: {
  materials: Mat[]
  fabrics: { name: string; qty: number; itemIds: number[]; rate?: number | null }[]
}): FactoryGroup {
  return {
    customer_name: '客户', product_name: '产品', product_quantity: 100,
    suppliers: [{
      supplier_name: '供应商1',
      fabrics: opts.fabrics.map((f) => ({
        fabric_name: f.name, specification: 'S1', unit: '米',
        quantity: f.qty, item_ids: f.itemIds, loss_rate: f.rate ?? null,
      })),
    }],
    skus: [
      {
        product_name: 'SKU-1', order_qty: 100,
        materials: opts.materials.map((m) => ({ ...m })),
      },
    ],
  }
}

function sharedGroups(baseA: number, baseB: number, stored: number, rate: number) {
  const g: FactoryGroup = {
    customer_name: '客户', product_name: '产品', product_quantity: 200,
    suppliers: [{
      supplier_name: '供应商1',
      fabrics: [{
        fabric_name: '共享布', specification: 'S1', unit: '米',
        quantity: stored, item_ids: [1], loss_rate: rate,
      }],
    }],
    skus: [
      {
        product_name: 'SKU-1', order_qty: 100,
        materials: [{
          supplier_name: '供应商1', material_name: '共享布', specification: 'S1',
          unit: '米', quantity: baseA, part_name: '',
        }],
      },
      {
        product_name: 'SKU-2', order_qty: 100,
        materials: [{
          supplier_name: '供应商1', material_name: '共享布', specification: 'S1',
          unit: '米', quantity: baseB, part_name: '',
        }],
      },
    ],
  }
  return g
}

function display(g: FactoryGroup, rateOf: (si: number, fi: number) => number) {
  return buildRowDisplayQuantities(g, buildPerSkuRows(g, 0), rateOf)
}

describe('buildRowDisplayQuantities', () => {
  it('2026-11-10 207/52 场景：落库 50 ≠ BOM 200.5 → 取落库加放 52', () => {
    const g = group({
      materials: [{
        supplier_name: '供应商1', material_name: '宝乐绒', specification: 'S1',
        unit: '米', quantity: 200.5, part_name: '',
      }],
      fabrics: [{ name: '宝乐绒', qty: 50, itemIds: [1], rate: 30 }],
    })
    expect(display(g, () => 30)).toEqual([52])
  })

  it('非手工（ΣBOM = 落库 60）：逐 SKU 推算 21 / 41', () => {
    expect(display(sharedGroups(20, 40, 60, 5), () => 5)).toEqual([21, 41])
  })

  it('手工（ΣBOM 60 ≠ 落库 65）：总量 66 按 1:2 分摊为 22 / 44', () => {
    const out = display(sharedGroups(20, 40, 65, 5), () => 5)
    expect(out).toEqual([22, 44])
    expect(out.reduce((s, v) => s + v, 0)).toBe(66)
  })

  it('落库为 0：所有行显示 0（不得回退 BOM 推算）', () => {
    expect(display(sharedGroups(20, 40, 0, 5), () => 5)).toEqual([0, 0])
  })

  it('BOM 全 0 但落库有量：总量等分，Σ = 总量', () => {
    const out = display(sharedGroups(0, 0, 10, 0), () => 0)
    expect(out).toEqual([5, 5])
  })

  it('无落库坐标（BOM 新增物料）：不加放，显示基准量', () => {
    const g = group({
      materials: [{
        supplier_name: '供应商1', material_name: '新加布', specification: 'S1',
        unit: '米', quantity: 20, part_name: '',
      }],
      fabrics: [],
    })
    const rows = buildPerSkuRows(g, 0)
    expect(buildRowDisplayQuantities(g, rows, () => 100)).toEqual([20])
  })
})

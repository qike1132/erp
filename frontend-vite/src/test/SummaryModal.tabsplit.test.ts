/**
 * SummaryModal 页签拆分回归（2026-09-19）。
 *
 * 背景：`SummaryModal.vue` 为压回质量门禁「单 SFC ≤400 行」阈值，把两个页签拆为
 * 子组件（`SummaryFactoryTab.vue` / `SummarySupplierTab.vue`）。本文件锁定拆分**不得**
 * 改变的两条契约 —— 都是拆分极易静默破坏、且既有 478 个用例**没有**覆盖的点：
 *
 *  G1【行为】损耗率防抖窗口内切换页签，输入不得丢失。
 *     拆分后防抖定时器若建在 `v-if` 之下的工厂子组件内，用户改完损耗率立刻切到
 *     「供应商」页签 → 子组件卸载 → 定时器回调 `emit` 无监听者 → 输入被静默丢弃、不落库。
 *     故防抖必须留在不随页签卸载的父组件（弹窗外壳）中。
 *     反向对照：不切页签时同样必须 emit，证明断言非恒真。
 *
 *  G2【样式】两张表的边框规则必须各自随组件作用域存在。
 *     拆分前由父组件 `table th, table td` 作用域规则提供边框；Vue 的 scoped 样式
 *     **不进入子组件内部**，子组件表格若不自带规则则边框静默消失。
 *     断言：两个子组件各自 `@use` 了共享 partial（源码级），且父组件不再依赖旧规则。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: vi.fn(),
    supplierSummaryExport: vi.fn(),
  },
}))

import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

// 源码级断言（样式归属）：用 Vite 的 ?raw 读原文，避免依赖 node:fs 类型
import factoryTabSrc from '@/views/purchase/components/SummaryFactoryTab.vue?raw'
import supplierTabSrc from '@/views/purchase/components/SummarySupplierTab.vue?raw'
import modalSrc from '@/views/purchase/components/SummaryModal.vue?raw'
import tablesPartialSrc from '@/styles/summary-tables.scss?raw'

const factoryData: FactorySummaryData = {
  success: true,
  order_count: 1,
  groups: [
    {
      customer_name: '客户A',
      product_name: '产品1',
      product_quantity: 100,
      suppliers: [
        {
          supplier_name: '供应商1',
          fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米' }],
        },
      ],
    },
  ],
}

function mountModal() {
  return mount(SummaryModal, {
    props: {
      open: true,
      factoryData,
      supplierData: null,
      editMode: false,
      lossRate: 0,
      orderCount: 1,
      supplierGroups: [],
    },
    global: { stubs: { UiDialog: { template: '<div><slot name="title" /><slot /></div>' } } },
  })
}

/** 越过 300ms 防抖窗口 */
const pastDebounce = () => new Promise((r) => setTimeout(r, 450))

describe('G1. 损耗率防抖不得因页签切换丢失', () => {
  it('改损耗率后**不切**页签 → emit applyLossRate（反向对照，证明断言非恒真）', async () => {
    const w = mountModal()
    await w.find('input[type="number"]').setValue('7')
    await pastDebounce()

    const emitted = w.emitted('applyLossRate')
    expect(emitted).toBeTruthy()
    expect(emitted![0]![0]).toBe(7)

    w.unmount()
  })

  it('改损耗率后**立即切**到供应商页签 → 仍须 emit applyLossRate（拆分核心回归）', async () => {
    const w = mountModal()
    await w.find('input[type="number"]').setValue('7')

    // 防抖窗口内切页签：工厂子组件被 v-if 卸载
    await w.findAll('.sm-tab-btn')[1]!.trigger('click')
    expect(w.findAll('.sm-tab-btn')[1]!.classes()).toContain('active')

    await pastDebounce()

    const emitted = w.emitted('applyLossRate')
    expect(emitted).toBeTruthy()
    expect(emitted![0]![0]).toBe(7)

    w.unmount()
  })

  it('损耗率夹取到 0..1000 后仍生效（负值 → 0，超限 → 1000）', async () => {
    const w = mountModal()
    const input = w.find('input[type="number"]')

    await input.setValue('-5')
    await pastDebounce()
    expect(w.emitted('applyLossRate')!.at(-1)![0]).toBe(0)

    await input.setValue('9999')
    await pastDebounce()
    expect(w.emitted('applyLossRate')!.at(-1)![0]).toBe(1000)

    w.unmount()
  })
})

describe('G2. 页签拆分后表格边框样式随子组件作用域存在', () => {
  it('两个页签子组件各自引入共享表格样式 partial', () => {
    for (const src of [factoryTabSrc, supplierTabSrc]) {
      expect(src).toContain("@use '@/styles/summary-tables.scss'")
    }
  })

  it('共享 partial 内含表格边框规则（拆分前由父组件提供）', () => {
    expect(tablesPartialSrc).toMatch(/table th,\s*table td\s*\{[^}]*border:\s*1px solid var\(--color-text\)/)
  })

  it('父组件不再自带 table 规则（已随页签下沉到子组件）', () => {
    expect(modalSrc).not.toMatch(/table th,\s*table td\s*\{/)
  })
})

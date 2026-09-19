/**
 * 汇总下单弹窗「点击遮罩/空白处不应关闭」行为级测试（BUG-2 修复）。
 *
 * 为什么单列一个文件：既有 useSummaryModal.test.ts 用 stub 把 UiDialog 换成普通 div，
 * 无法验证遮罩交互。这里挂载**真实** UiDialog（reka-ui Dialog）走完整 emit 链：
 *   document pointerdown(外侧) → DismissableLayer.pointerDownOutside
 *   → interactOutside → UiDialog.onInteractOutside → (closeOnOverlayClick=false 则 preventDefault)
 *   → 决定是否 emit dismiss → DialogRoot update:open → SummaryModal close
 *
 * 反向对照（默认 closeOnOverlayClick=true 必须触发 update:open）证明断言有效、非恒真。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick, defineComponent } from 'vue'

// 隔离外部依赖：SummaryModal → useSummaryModal 顶层 import purchaseApi from '@/api'
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

import UiDialog from '@/components/ui/UiDialog.vue'
import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

/**
 * reka-ui DismissableLayer 在 window.setTimeout(0) 后才把 document 级 pointerdown
 * 监听挂上；事件回调又在 nextTick 后决定是否 dismiss。用真实宏任务 + 微任务让
 * 「监听就绪 / 决策完成」都发生。
 */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await flushPromises()
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await flushPromises()
  await nextTick()
}

/** 在弹窗之外的 document.body 上派发一次可取消的 pointerdown（模拟点击遮罩外侧空白） */
function pointerDownOutside() {
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }))
}

function mountDialog(props: Record<string, unknown> = {}) {
  return mount(UiDialog, {
    props: { open: true, ...props },
    slots: { default: '<div class="dlg-body">内容</div>' },
    attachTo: document.body,
  })
}

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

function mountSummary() {
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
    attachTo: document.body,
  })
}

describe('BUG-2「点击遮罩/空白处不应关闭」— 真实 UiDialog 行为级验证', () => {
  it('【反向对照】默认 closeOnOverlayClick=true → 遮罩外侧 pointerdown 触发 update:open(false)', async () => {
    const wrapper = mountDialog()
    await settle()
    pointerDownOutside()
    await settle()

    const emitted = wrapper.emitted('update:open')
    expect(emitted).toBeTruthy()
    expect((emitted as unknown[][])[0]![0]).toBe(false)

    wrapper.unmount()
  })

  it('closeOnOverlayClick=false → 遮罩外侧 pointerdown 不触发 update:open', async () => {
    const wrapper = mountDialog({ closeOnOverlayClick: false })
    await settle()
    pointerDownOutside()
    await settle()

    expect(wrapper.emitted('update:open')).toBeFalsy()

    wrapper.unmount()
  })

  it('SummaryModal 的 UiDialog 收到 closeOnOverlayClick === false（prop 透传）', () => {
    const wrapper = mountSummary()
    expect(wrapper.findComponent(UiDialog).props('closeOnOverlayClick')).toBe(false)
    wrapper.unmount()
  })

  it('【行为级】真实 UiDialog 下，遮罩外侧 pointerdown 不触发 close 事件', async () => {
    const wrapper = mountSummary()
    await settle()
    pointerDownOutside()
    await settle()

    expect(wrapper.emitted('close')).toBeFalsy()

    wrapper.unmount()
  })

  it('【链路补证】UiDialog 发出 update:open 时 SummaryModal 转发 close（确认抑制来自该 prop）', async () => {
    const UiDialogStub = defineComponent({
      name: 'UiDialogStub',
      props: {
        open: { type: Boolean, default: false },
        closeOnOverlayClick: { type: Boolean, default: true },
      },
      emits: ['update:open'],
      template: '<div class="ui-dialog-stub"><slot name="title" /><slot /></div>',
    })
    // 覆盖本文件顶部 vi.mock 无关；仅替换 UiDialog 以单独验证「update:open → close」接线
    const wrapper = mount(SummaryModal, {
      props: {
        open: true,
        factoryData,
        supplierData: null,
        editMode: false,
        lossRate: 0,
        orderCount: 1,
        supplierGroups: [],
      },
      global: { stubs: { UiDialog: UiDialogStub } },
    })

    wrapper.findComponent(UiDialogStub).vm.$emit('update:open', false)
    await nextTick()

    expect(wrapper.emitted('close')).toBeTruthy()

    wrapper.unmount()
  })
})

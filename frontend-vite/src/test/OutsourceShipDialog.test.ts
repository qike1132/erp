/**
 * OutsourceShipDialog 批量发货「双栏选购清单」回归
 *
 * 交互模型：左栏点卡片=加入清单（选中自动展开为右栏可编辑卡片），右栏核对数量/整行取消/✕ 移出；
 * 底栏实时合计；「生成发货单」→ 底栏原地切换确认态；成功=发货单清单，失败=错误明细+返回修改。
 * 安全底线：默认全不选、数量校验、提交中防关闭。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import OutsourceShipDialog from '@/views/outsource/components/OutsourceShipDialog.vue'

const shippableMock = vi.fn()
const createMergedShipmentMock = vi.fn()

vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))
vi.mock('@/api/outsource', () => ({
  outsourceApi: {
    shippable: (...args: unknown[]) => shippableMock(...args),
    createMergedShipment: (...args: unknown[]) => createMergedShipmentMock(...args),
  },
}))

// emits 必须声明：否则父组件 @click 经 attrs 透传成原生监听 + $emit 双触发（历史"2 times"根因）
function mountDialog() {
  return mount(OutsourceShipDialog, {
    global: {
      stubs: {
        FontAwesomeIcon: { template: '<i />' },
        UiDialog: { props: ['title'], template: '<div class="ui-dialog"><slot /><slot name="footer" /></div>' },
        UiButton: {
          props: ['variant', 'disabled'],
          emits: ['click'],
          template: '<button type="button" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
        UiSpinner: { template: '<div />' },
      },
    },
  })
}

function proc(over: Record<string, unknown> = {}) {
  const merged = {
    process_id: 1, order_id: 1, order_no: 'PO-A', customer: '客户A',
    product_name: 'SKU-A', process_type: '电绣', target_qty: 100,
    shipped_qty: 0, remaining: 100,
    ...over,
  }
  // 夹具自洽：真实数据中 remaining = target_qty − shipped_qty。
  // 未显式指定 target_qty 时由 remaining 反推，避免总量与剩余互相矛盾。
  if (!('target_qty' in over)) {
    merged.target_qty = Number(merged.remaining) + Number(merged.shipped_qty)
  }
  return merged
}

const THREE_ROWS_TWO_ORDERS = [
  proc({ process_id: 1, order_id: 1, order_no: 'PO-A', customer: '客户A', product_name: 'SKU-A', process_type: '电绣', remaining: 100 }),
  proc({ process_id: 2, order_id: 1, order_no: 'PO-A', customer: '客户A', product_name: 'SKU-A', process_type: '转印', remaining: 100 }),
  proc({ process_id: 3, order_id: 2, order_no: 'PO-B', customer: '客户B', product_name: 'SKU-B', process_type: '转印', remaining: 50 }),
]

async function openAndLoad(wrapper: ReturnType<typeof mountDialog>) {
  await wrapper.setProps({ open: true })
  await flushPromises()
}

function btn(wrapper: ReturnType<typeof mountDialog>, text: string) {
  return wrapper.findAll('button').find((b) => b.text().includes(text))
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe('OutsourceShipDialog 双栏选购清单', () => {
  it('初始态：左栏按客户+产品聚合、清单空态、生成按钮禁用（防误触回归）', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    // 左栏：客户A/SKU-A 与 客户B/SKU-B 两项，均未选中
    expect(wrapper.findAll('.osw-card').length).toBe(2)
    expect(wrapper.findAll('.osw-card.is-on').length).toBe(0)
    expect(wrapper.find('.osw-l-meta').text()).toContain('待发货产品 2 项')

    // 右栏：空态提示 + 汇总为零 + 生成禁用
    expect(wrapper.find('.osw-cart-empty').exists()).toBe(true)
    expect(wrapper.find('.osw-chip').text()).toContain('0 项')
    expect(wrapper.find('.osw-bar-info').text()).toContain('0 件')
    expect(btn(wrapper, '生成发货单')!.attributes('disabled')).toBeDefined()
  })

  it('点卡片=加入清单（按 SKU 成卡、每道工序一行独立数量）；再点=移出', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    await wrapper.findAll('.osw-card')[0]!.trigger('click')
    await flushPromises()

    // 加入清单 + 卡片高亮 + 汇总
    expect(wrapper.findAll('.osw-card.is-on').length).toBe(1)
    expect(wrapper.findAll('.osw-cart-card').length).toBe(1)
    expect(wrapper.find('.osw-chip').text()).toContain('1 项')
    expect(wrapper.find('.osw-bar-info').text()).toContain('200 件')
    // SKU-A：SKU 名只出现一次，2 道工序横向排列、各有独立数量输入框
    expect(wrapper.find('.osw-cart-title').text()).toBe('SKU-A')
    expect(wrapper.findAll('.osw-proc-grid').length).toBe(1)
    const cells = wrapper.findAll('.osw-cell')
    expect(cells.length).toBe(2)
    expect(cells.map((r) => r.find('.osw-proc').text())).toEqual(['电绣', '转印'])
    const qtys = wrapper.findAll('.osw-qty')
    expect(qtys.length).toBe(2)
    expect(qtys.map((q) => (q.element as HTMLInputElement).value)).toEqual(['100', '100'])

    // 再点同卡片 → 移出清单
    await wrapper.findAll('.osw-card')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.osw-cart-card').length).toBe(0)
    expect(wrapper.find('.osw-cart-empty').exists()).toBe(true)
  })

  it('每道工序可单独取消勾选（不发该工序），卡片保留可恢复；✕ 移出整个 SKU', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    await wrapper.findAll('.osw-card')[0]!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.osw-bar-info').text()).toContain('200 件')

    // 取消第 1 道工序 → 该格置灰、合计减半；卡片保留（便于再勾回来）
    const rowCbx = (i: number) => wrapper.findAll('.osw-cell')[i]!.find('.osw-cbx')
    await rowCbx(0).setValue(false)
    await flushPromises()
    expect(wrapper.findAll('.osw-cell')[0]!.classes()).toContain('is-off')
    expect(wrapper.find('.osw-bar-info').text()).toContain('100 件')
    expect(wrapper.find('.osw-bar-info').text()).toContain('1 道工序')
    expect(wrapper.findAll('.osw-cart-card').length).toBe(1)
    // 取消勾选后该格剩余不扣减，恢复为剩余合计
    expect(wrapper.findAll('.osw-cell')[0]!.find('.osw-remain b').text()).toBe('100')

    // 再勾选 → 恢复
    await rowCbx(0).setValue(true)
    await flushPromises()
    expect(wrapper.find('.osw-bar-info').text()).toContain('200 件')

    // 两道工序全取消 → 合计归零、生成禁用，但卡片仍在（可恢复）
    await rowCbx(0).setValue(false)
    await flushPromises()
    await wrapper.findAll('.osw-cell')[1]!.find('.osw-cbx').setValue(false)
    await flushPromises()
    expect(wrapper.find('.osw-bar-info').text()).toContain('0 件')
    expect(btn(wrapper, '生成发货单')!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.osw-cart-card').length).toBe(1)

    // ✕ 移出整个 SKU
    await wrapper.find('.osw-rm').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.osw-cart-card').length).toBe(0)
  })

  it('每道工序独立填数量；非法值自动纠正，修正后恢复', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    await wrapper.findAll('.osw-card')[0]!.trigger('click')
    await flushPromises()

    // 只改第 1 道工序 → 第 2 道不受影响（需求 3）
    const qty0 = () => wrapper.findAll('.osw-qty')[0]!
    await qty0().setValue(50)
    await flushPromises()
    expect(wrapper.find('.osw-bar-info').text()).toContain('150 件')
    expect((wrapper.findAll('.osw-qty')[1]!.element as HTMLInputElement).value).toBe('100')

    // 实时剩余：默认数量=剩余合计，故发完后剩余为 0；改小数量后应剩回差额
    const remain = (i: number) => wrapper.findAll('.osw-cell')[i]!.find('.osw-remain b').text()
    expect(remain(0)).toBe('50')
    expect(remain(1)).toBe('0')

    // 数量改为 0 → 自动恢复为该工序剩余合计上限（100），不产生非法态
    await qty0().setValue(0)
    await flushPromises()
    expect((qty0().element as HTMLInputElement).value).toBe('100')
    expect(qty0().classes()).not.toContain('is-invalid')
    expect(wrapper.find('.osw-bar-err').exists()).toBe(false)

    // 负数 → 同样恢复为上限
    await qty0().setValue(-5)
    await flushPromises()
    expect((qty0().element as HTMLInputElement).value).toBe('100')

    // 修正为合法值 → 合计正确
    await qty0().setValue(50)
    expect(qty0().classes()).not.toContain('is-invalid')
    expect(wrapper.find('.osw-bar-err').exists()).toBe(false)
    expect(wrapper.find('.osw-bar-info').text()).toContain('150 件')
    expect(btn(wrapper, '生成发货单')!.attributes('disabled')).toBeUndefined()
  })

  it('数量非法时自动纠正：超限钳制、小数向下取整，合计始终正确', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)
    await wrapper.findAll('.osw-card')[0]!.trigger('click')
    await flushPromises()
    // 初始：2 道工序各 100，共 200
    expect(wrapper.find('.osw-bar-info').text()).toContain('200 件')

    const qty0 = () => wrapper.findAll('.osw-qty')[0]!
    // 填 999（上限 100）→ 自动钳制为 100，不产生非法态，合计不变
    await qty0().setValue(999)
    await flushPromises()
    expect((qty0().element as HTMLInputElement).value).toBe('100')
    expect(qty0().classes()).not.toContain('is-invalid')
    expect(wrapper.find('.osw-bar-err').exists()).toBe(false)
    expect(wrapper.find('.osw-bar-info').text()).toContain('200 件')
    expect(btn(wrapper, '生成发货单')!.attributes('disabled')).toBeUndefined()

    // 小数 1.5 → 向下取整为 1（不虚报），合计 1 + 100 = 101
    await qty0().setValue(1.5)
    await flushPromises()
    expect((qty0().element as HTMLInputElement).value).toBe('1')
    expect(qty0().classes()).not.toContain('is-invalid')
    expect(wrapper.find('.osw-bar-err').exists()).toBe(false)
    expect(wrapper.find('.osw-bar-info').text()).toContain('101 件')

    // 小数 1.9 → 仍向下取整为 1（不进位）
    await qty0().setValue(1.9)
    await flushPromises()
    expect((qty0().element as HTMLInputElement).value).toBe('1')

    // 恢复合法值
    await qty0().setValue(100)
    await flushPromises()
    expect(wrapper.find('.osw-bar-info').text()).toContain('200 件')
  })

  it('完整流：选两单→生成→确认态→提交，payload 平铺为单明细数组', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    createMergedShipmentMock.mockResolvedValue({
      id: 1, shipment_no: 'FH-20260920-0001', order_id: null, customer: null,
      status: 'shipped', item_count: 3, total_shipped: 200,
    })

    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    // 加入两单；订单 A 第 1 道工序改 50（第 2 道保持 100，验证逐工序独立）
    await wrapper.findAll('.osw-card')[0]!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.osw-card')[1]!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.osw-qty')[0]!.setValue(50)
    await flushPromises()

    // 汇总 + 按钮带汇总（A: 50 + 100 = 150，B: 50 → 共 200）
    expect(wrapper.find('.osw-bar-info').text()).toContain('200 件')
    await btn(wrapper, '生成发货单（200 件）')!.trigger('click')
    await flushPromises()

    // 确认态：底栏原地切换（不跳页）
    expect(wrapper.find('.osw-bar--confirm').exists()).toBe(true)
    expect(wrapper.text()).toContain('将生成 1 张发货单')

    // 确认发货 → 成功面板
    await btn(wrapper, '确认发货')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('发货完成：已生成 1 张发货单')
    expect(wrapper.text()).toContain('FH-20260920-0001')
    expect(wrapper.text()).toContain('待贝乐收货')

    // payload 平铺为单明细数组（跨订单合并，不再按订单分组）
    expect(createMergedShipmentMock).toHaveBeenCalledTimes(1)
    const payload = createMergedShipmentMock.mock.calls[0]![0] as {
      process_id: number
      quantity: number
    }[]
    expect(payload).toEqual([
      { process_id: 1, quantity: 50 },
      { process_id: 2, quantity: 100 },
      { process_id: 3, quantity: 50 },
    ])
  })

  it('失败态：错误明细 + 返回修改保留已填数据', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    createMergedShipmentMock.mockRejectedValue({
      response: { data: { detail: '外发工序 3：发货数量超过剩余数量（剩余 50）' } },
    })

    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    await wrapper.findAll('.osw-card')[0]!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.osw-card')[1]!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.osw-qty')[0]!.setValue(50)
    await flushPromises()
    await btn(wrapper, '生成发货单（200 件）')!.trigger('click')
    await flushPromises()
    await btn(wrapper, '确认发货')!.trigger('click')
    await flushPromises()

    // 失败面板
    expect(wrapper.text()).toContain('发货失败（整批已回滚，数据未变更）')
    expect(wrapper.text()).toContain('外发工序 3：发货数量超过剩余数量（剩余 50）')

    // 返回修改：回到双栏编辑态，勾选与数量保留
    await btn(wrapper, '返回修改')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.osw-cart-card').length).toBe(2)
    expect((wrapper.findAll('.osw-qty')[0]!.element as HTMLInputElement).value).toBe('50')
    expect(wrapper.find('.osw-bar').exists()).toBe(true)
  })

  it('提交中：遮罩进度反馈，完成后切换成功面板', async () => {
    let resolveBatch!: (v: unknown) => void
    createMergedShipmentMock.mockImplementation(
      () => new Promise((resolve) => { resolveBatch = resolve }),
    )
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    await wrapper.findAll('.osw-card')[0]!.trigger('click')
    await flushPromises()
    await btn(wrapper, '生成发货单')!.trigger('click')
    await flushPromises()
    await btn(wrapper, '确认发货')!.trigger('click')

    // 请求挂起中：遮罩出现
    expect(wrapper.find('.osw-submitting').exists()).toBe(true)
    expect(wrapper.find('.osw-submitting').text()).toContain('正在生成发货单')

    resolveBatch({
      id: 1, shipment_no: 'FH-20260920-0001', order_id: null, customer: null,
      status: 'shipped', item_count: 2, total_shipped: 200,
    })
    await flushPromises()
    expect(wrapper.find('.osw-submitting').exists()).toBe(false)
    expect(wrapper.text()).toContain('发货完成：已生成 1 张发货单')
  })

  it('左栏筛选：关键字过滤产品列表；无客户下拉', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    // 关键字过滤（按产品名）
    await wrapper.find('.osw-search input').setValue('SKU-B')
    expect(wrapper.findAll('.osw-card').length).toBe(1)
    expect(wrapper.find('.osw-l-meta').text()).toContain('待发货产品 1 项')
    await wrapper.find('.osw-search input').setValue('')
    expect(wrapper.findAll('.osw-card').length).toBe(2)

    // 客户下拉已移除
    expect(wrapper.find('.osw-cust-select').exists()).toBe(false)

    // 全选（仅加入当前筛选结果）
    await wrapper.find('.osw-search input').setValue('SKU-B')
    await btn(wrapper, '全选')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.osw-cart-card').length).toBe(1)
    expect(wrapper.find('.osw-bar-info').text()).toContain('50 件')

    // 重复全选不应累加数量（回归：曾把已在清单的产品数量翻倍）
    await btn(wrapper, '全选')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.osw-bar-info').text()).toContain('50 件')
    expect((wrapper.find('.osw-qty').element as HTMLInputElement).value).toBe('50')
  })

  it('左栏卡片只展示产品名，不含客户名 / PO 号 / 剩余未发', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    // 按产品名定位卡片（不依赖排序）
    const cards = wrapper.findAll('.osw-card')
    const byName = (n: string) => cards.find((c) => c.find('.osw-prod-name').text() === n)!
    const cardA = byName('SKU-A')
    // 客户列已移除
    expect(cardA.find('.osw-card-cust').exists()).toBe(false)
    expect(cardA.text()).not.toContain('客户A')
    // 不展示 PO 号，也不展示剩余未发
    expect(cardA.text()).not.toContain('PO-A')
    expect(cardA.text()).not.toContain('剩')
    expect(cardA.find('.osw-prod-qty').exists()).toBe(false)

    const cardB = byName('SKU-B')
    expect(cardB.text()).not.toContain('客户B')
    expect(cardB.text()).not.toContain('PO-B')
    expect(cardB.text()).not.toContain('剩')
  })

  it('左栏每项为单行布局：勾选框 + 产品名 + 角标', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    const card = wrapper.find('.osw-card')
    // 勾选框与产品名是同一行的直接子元素（无中间容器）
    const directChildren = Array.from(card.element.children).map((el) => el.className)
    expect(directChildren.some((c) => c.includes('osw-prod-name'))).toBe(true)
    expect(card.find('input.osw-cbx').exists()).toBe(true)
    // 不再有分行容器
    expect(card.find('.osw-card-main').exists()).toBe(false)
    expect(card.find('.osw-card-top').exists()).toBe(false)
  })

  it('左栏列表上方只有「产品名称」表头', async () => {
    shippableMock.mockResolvedValue(THREE_ROWS_TWO_ORDERS)
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    const head = wrapper.find('.osw-l-head')
    expect(head.exists()).toBe(true)
    expect(head.find('.osw-l-head-prod').text()).toBe('产品名称')
    // 「客户名称」表头已移除
    expect(head.find('.osw-l-head-cust').exists()).toBe(false)
    expect(head.text()).not.toContain('客户名称')
    // 「剩余未发」表头已移除
    expect(head.find('.osw-l-head-qty').exists()).toBe(false)
    expect(head.text()).not.toContain('剩余未发')
    // 表头在滚动容器内、且位于首个卡片之前（sticky 保证与卡片同宽对齐）
    const listHtml = wrapper.find('.osw-l-list').html()
    expect(listHtml.indexOf('osw-l-head')).toBeLessThan(listHtml.indexOf('osw-card'))
  })

  it('同一客户同产品跨多订单合并为一项并提示订单数', async () => {
    shippableMock.mockResolvedValue([
      proc({ process_id: 1, order_id: 1, order_no: 'PO-A', customer: '客户A', product_name: '毛绒盲盒', process_type: '裁剪', remaining: 1000 }),
      proc({ process_id: 2, order_id: 1, order_no: 'PO-A', customer: '客户A', product_name: '毛绒盲盒', process_type: '电绣', remaining: 1000 }),
      proc({ process_id: 3, order_id: 2, order_no: 'PO-B', customer: '客户A', product_name: '毛绒盲盒', process_type: '缝制', remaining: 2000 }),
      proc({ process_id: 4, order_id: 2, order_no: 'PO-B', customer: '客户A', product_name: '抱枕靠垫', process_type: '包装', remaining: 500 }),
    ])
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    // 「毛绒盲盒」跨 PO-A / PO-B 两张订单 → 合并为一项；与「抱枕靠垫」共 2 项
    const cards = wrapper.findAll('.osw-card')
    expect(cards.length).toBe(2)

    // 按产品名定位卡片（不依赖排序）
    const byName = (n: string) => cards.find((c) => c.find('.osw-prod-name').text() === n)!
    const blindBox = byName('毛绒盲盒')
    // 跨订单角标（单行紧凑文案）
    expect(blindBox.find('.osw-prod-orders').text()).toBe('2单')

    // 单订单产品无跨订单提示
    const cushion = byName('抱枕靠垫')
    expect(cushion.find('.osw-prod-orders').exists()).toBe(false)

    // 勾选跨订单产品 → 只勾选该产品的工序
    await blindBox.trigger('click')
    await flushPromises()
    // 清单按 SKU 合并为 1 张卡；卡内 3 道不同工序横向排列在同一行容器中
    expect(wrapper.findAll('.osw-cart-card').length).toBe(1)
    expect(wrapper.find('.osw-cart-title').text()).toBe('毛绒盲盒')
    expect(wrapper.findAll('.osw-proc-grid').length).toBe(1)
    expect(wrapper.findAll('.osw-cell').map((r) => r.find('.osw-proc').text()))
      .toEqual(['裁剪', '电绣', '缝制'])
    expect(wrapper.find('.osw-cart-orders').text()).toBe('2 单合并')
    expect(wrapper.find('.osw-bar-info').text()).toContain('3 道工序')
    // 底栏按工序求和（1000+1000+2000），与系统「发货总量」口径一致（各工序明细求和）
    expect(wrapper.find('.osw-bar-info').text()).toContain('4,000 件')
    // 卡头合计 = 该产品跨订单总数
    expect(wrapper.find('.osw-cart-sum').text()).toContain('4,000')

    // 只显示已选产品：PO-B 的「抱枕靠垫」未勾选 → 不出现在清单中
    const cartText = wrapper.find('.osw-r-list').text()
    expect(cartText).toContain('毛绒盲盒')
    expect(cartText).not.toContain('抱枕靠垫')
  })

  it('同一 SKU 的同一工序跨订单合并为一行，数量按订单顺序自动拆分', async () => {
    shippableMock.mockResolvedValue([
      proc({ process_id: 1, order_id: 1, order_no: 'PO-A', customer: '客户A', product_name: '变形金刚', process_type: '转印', remaining: 100 }),
      proc({ process_id: 2, order_id: 2, order_no: 'PO-B', customer: '客户B', product_name: '变形金刚', process_type: '转印', remaining: 200 }),
      proc({ process_id: 3, order_id: 3, order_no: 'PO-C', customer: '客户C', product_name: '变形金刚', process_type: '转印', remaining: 300 }),
    ])
    createMergedShipmentMock.mockResolvedValue({
      id: 1, shipment_no: 'FH-1', order_id: null, customer: null,
      status: 'shipped', item_count: 1, total_shipped: 250,
    })
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    // 左栏也按产品名聚合 → 3 个客户下的同一产品合并为 1 项
    expect(wrapper.findAll('.osw-card').length).toBe(1)
    expect(wrapper.find('.osw-prod-name').text()).toBe('变形金刚')
    expect(wrapper.find('.osw-prod-orders').text()).toBe('3单')

    // 全选 → 清单 1 张卡、1 格（3 张订单的「转印」合并）
    await btn(wrapper, '全选')!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.osw-cart-card').length).toBe(1)
    expect(wrapper.find('.osw-cart-title').text()).toBe('变形金刚')
    expect(wrapper.find('.osw-cart-orders').text()).toBe('3 单合并')
    expect(wrapper.findAll('.osw-proc-grid').length).toBe(1)
    expect(wrapper.findAll('.osw-cell').length).toBe(1)
    expect(wrapper.find('.osw-proc').text()).toBe('转印')
    // 总量/剩余合计 = 跨订单合计（100+200+300）；数量默认取该合计，故发完后剩余为 0
    expect(wrapper.find('.osw-total b').text()).toBe('600')
    expect(wrapper.find('.osw-remain b').text()).toBe('0')
    expect((wrapper.find('.osw-qty').element as HTMLInputElement).value).toBe('600')
    expect(wrapper.find('.osw-cart-sum').text()).toContain('600')

    // 填 250 → 发完后剩余 350（实时预览），并按订单顺序拆分
    await wrapper.find('.osw-qty').setValue(250)
    await flushPromises()
    expect(wrapper.find('.osw-remain b').text()).toBe('350')
    expect(wrapper.find('.osw-cart-sum').text()).toContain('250')
    // 涉及订单数 = 实际拆分到的 2 单
    expect(wrapper.find('.osw-bar-info').text()).toContain('2 单')

    await btn(wrapper, '生成发货单（250 件）')!.trigger('click')
    await flushPromises()
    await btn(wrapper, '确认发货')!.trigger('click')
    await flushPromises()

    const payload = createMergedShipmentMock.mock.calls[0]![0] as {
      process_id: number
      quantity: number
    }[]
    expect(payload).toEqual([
      { process_id: 1, quantity: 100 },
      { process_id: 2, quantity: 150 },
    ])
  })

  it('合并行数量超过跨订单剩余合计时自动钳制到合计上限', async () => {
    shippableMock.mockResolvedValue([
      proc({ process_id: 1, order_id: 1, order_no: 'PO-A', product_name: '变形金刚', process_type: '转印', remaining: 100 }),
      proc({ process_id: 2, order_id: 2, order_no: 'PO-B', product_name: '变形金刚', process_type: '转印', remaining: 200 }),
    ])
    const wrapper = mountDialog()
    await openAndLoad(wrapper)
    await wrapper.find('.osw-card').trigger('click')
    await flushPromises()

    const qty = () => wrapper.find('.osw-qty')
    expect(qty().classes()).not.toContain('is-invalid')

    // 300 合法（= 跨订单上限）；301 超出 → 自动钳制回 300，不进入非法态
    await qty().setValue(300)
    await flushPromises()
    expect(qty().classes()).not.toContain('is-invalid')
    await qty().setValue(301)
    await flushPromises()
    expect((qty().element as HTMLInputElement).value).toBe('300')
    expect(qty().classes()).not.toContain('is-invalid')
    expect(wrapper.find('.osw-bar-err').exists()).toBe(false)
    expect(btn(wrapper, '生成发货单')!.attributes('disabled')).toBeUndefined()
  })

  it('同一 SKU 多工序在同一行内横向展示，每格数量独立可改', async () => {
    // 「企鹅的订单」6 道工序、剩余均为 9,626（与真实数据一致）
    shippableMock.mockResolvedValue([
      proc({ process_id: 1, order_id: 5, order_no: 'PO-P', customer: '名创优品', product_name: '企鹅的订单', process_type: '裁剪', remaining: 9626 }),
      proc({ process_id: 2, order_id: 5, order_no: 'PO-P', customer: '名创优品', product_name: '企鹅的订单', process_type: '电绣', remaining: 9626 }),
      proc({ process_id: 3, order_id: 5, order_no: 'PO-P', customer: '名创优品', product_name: '企鹅的订单', process_type: '缝制', remaining: 9626 }),
      proc({ process_id: 4, order_id: 5, order_no: 'PO-P', customer: '名创优品', product_name: '企鹅的订单', process_type: '转印', remaining: 9626 }),
      proc({ process_id: 5, order_id: 5, order_no: 'PO-P', customer: '名创优品', product_name: '企鹅的订单', process_type: '配件', remaining: 9626 }),
      proc({ process_id: 6, order_id: 5, order_no: 'PO-P', customer: '名创优品', product_name: '企鹅的订单', process_type: '包装', remaining: 9626 }),
    ])
    createMergedShipmentMock.mockResolvedValue({
      id: 1, shipment_no: 'FH-20260920-0009', order_id: null, customer: null,
      status: 'shipped', item_count: 6, total_shipped: 48230,
    })

    const wrapper = mountDialog()
    await openAndLoad(wrapper)
    await wrapper.find('.osw-card').trigger('click')
    await flushPromises()

    // SKU 名只出现一次；6 道工序横向排列在同一行容器内、各有独立数量框
    expect(wrapper.findAll('.osw-cart-card').length).toBe(1)
    expect(wrapper.find('.osw-cart-title').text()).toBe('企鹅的订单')
    expect(wrapper.findAll('.osw-proc-grid').length).toBe(1)
    const cells = wrapper.findAll('.osw-cell')
    expect(cells.length).toBe(6)
    expect(cells.map((r) => r.find('.osw-proc').text())).toEqual(['裁剪', '电绣', '缝制', '转印', '配件', '包装'])
    expect(wrapper.findAll('.osw-qty').length).toBe(6)
    // 每格显示订单总量与发完后剩余；默认数量=剩余合计，故初始发完后剩余为 0
    expect(cells[0]!.find('.osw-total b').text()).toBe('9,626')
    expect(cells[0]!.find('.osw-remain b').text()).toBe('0')
    expect(wrapper.find('.osw-bar-info').text()).toContain('57,756 件')

    // 只改第 1 道工序为 100 → 仅该行变化（9,626×5 + 100）
    await wrapper.findAll('.osw-qty')[0]!.setValue(100)
    await flushPromises()
    expect(wrapper.find('.osw-bar-info').text()).toContain('48,230 件')
    await btn(wrapper, '生成发货单（48,230 件）')!.trigger('click')
    await flushPromises()
    await btn(wrapper, '确认发货')!.trigger('click')
    await flushPromises()

    const payload = createMergedShipmentMock.mock.calls[0]![0] as {
      process_id: number
      quantity: number
    }[]
    expect(payload.length).toBe(6)
    expect(payload[0]).toEqual({ process_id: 1, quantity: 100 })
    expect(payload.slice(1).every((it) => it.quantity === 9626)).toBe(true)
  })

  it('产品名为空时回退占位文案，长名称完整渲染不截断', async () => {
    const LONG = 'Nommi糯米儿-宝藏收藏家系列毛绒盲盒'
    shippableMock.mockResolvedValue([
      proc({ process_id: 1, order_id: 11, order_no: 'PO-L', customer: '名创优品海外', product_name: LONG, target_qty: 42908, remaining: 42908 }),
      proc({ process_id: 2, order_id: 11, order_no: 'PO-L', customer: '名创优品海外', product_name: null, target_qty: 10, remaining: 10 }),
    ])
    const wrapper = mountDialog()
    await openAndLoad(wrapper)

    const names = wrapper.findAll('.osw-prod-name').map((n) => n.text())
    expect(names.length).toBe(2)
    // 长名称完整呈现（文本未被截断）
    expect(names).toContain(LONG)
    // 空名称回退占位
    expect(names).toContain('未命名产品')
  })
})
/**
 * UiDataTable 空态（2026-10-14 /stock-return「表头下面多了一条横线」回归）。
 *
 * 背景：UiDataTable 声明了 `emptyMessage` prop（默认「暂无数据」），多个视图也在传
 * `empty-message`，但这个 prop 从来没绑到 PrimeVue 的 <DataTable> 上 —— 空表渲染出的
 * 单元格是空的；同时尺寸段 `emptyMessage`（py-12）挂在 <tr> 上，而浏览器对表格行
 * 忽略垂直 padding。两者叠加：空表体塌成 ~24px 一条，表格下边框紧贴表头下边框，
 * 用户看到的就是「表头下面凭空多了一条横线」（退货页当时 0 条记录，必然命中）。
 *
 * 这里锁三层：文案真的渲染出来、尺寸挂在单元格上、PT 段名分工不再写错。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import UiDataTable from '@/components/ui/UiDataTable.vue'

const COLS = [{ field: 'name', header: '名称' }]
const ROWS = [{ id: 1, name: '甲' }]

function mountTable(props: { data: Record<string, unknown>[] } & Record<string, unknown>) {
  return mount(UiDataTable, {
    props: { columns: COLS, ...props },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

describe('UiDataTable 空态', () => {
  it('空数据时把 empty-message 文案渲染出来，而不是一片空白', () => {
    const w = mountTable({ data: [], emptyMessage: '暂无退货记录' })

    expect(w.text()).toContain('暂无退货记录')
  })

  it('未传 empty-message 时用默认文案「暂无数据」', () => {
    expect(mountTable({ data: [] }).text()).toContain('暂无数据')
  })

  it('有数据时不出现空态文案（文案只属于空态）', () => {
    const w = mountTable({ data: ROWS, emptyMessage: '暂无退货记录' })

    expect(w.text()).toContain('甲')
    expect(w.text()).not.toContain('暂无退货记录')
  })

  it('空态高度挂在单元格上（<tr> 的 padding 不生效，塌成一条就是那个「横线」）', () => {
    const td = mountTable({ data: [] }).find('td[data-pc-section="emptymessagecell"]')

    expect(td.exists()).toBe(true)
    // 96px = py-12（48px×2）的原意；写死在单元格上，不依赖 tailwind 工具类优先级
    expect(td.attributes('style') ?? '').toContain('height: 96px')
  })

  it('父级传 #empty 插槽时以插槽为准，不被默认文案顶掉', () => {
    const w = mount(UiDataTable, {
      props: { data: [], columns: COLS },
      slots: { empty: '<div class="my-empty">自定义空态</div>' },
      global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
    })

    expect(w.find('.my-empty').exists()).toBe(true)
    expect(w.text()).toContain('自定义空态')
    expect(w.text()).not.toContain('暂无数据')
  })

  it('不再向 DataTable 透传不存在的 responsive 属性（PrimeVue 4 无此 prop，纯 DOM 噪音）', () => {
    const w = mountTable({ data: ROWS })
    const root = w.find('[data-pc-name="datatable"]')

    expect(root.exists()).toBe(true)
    expect(root.attributes('responsive')).toBeUndefined()
  })

  it('PT 契约：尺寸段在 emptyMessageCell，emptyMessage 段只管文案', () => {
    const datatable = plushCutePT.datatable
    if (typeof datatable !== 'object' || datatable === null) {
      throw new Error('datatable PT 应为静态对象')
    }
    const trSection = datatable.emptyMessage
    const trText = typeof trSection === 'string' ? trSection : JSON.stringify(trSection)

    // py-12 留在 tr 段上等于没写（表格行不吃 padding），空态会再次塌成一条
    expect(trText).not.toContain('py-12')
    expect(datatable.emptyMessageCell).toBeDefined()
    expect(JSON.stringify(datatable.emptyMessageCell)).toContain('96px')
  })
})

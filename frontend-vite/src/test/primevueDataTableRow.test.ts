/**
 * PrimeVue DataTable 的行样式（全站表格共有）。
 *
 * 背景：`primevue-pt.ts` 原先把行分隔线与 hover 写在 `datatable.row` 上，
 * 但 PrimeVue 的 `row` 段指的是「Row 辅助组件」（展开行/分组行那套），
 * `<tr>` 本体对应的是 `bodyRow`。段名写错 ⇒ 行样式从来没落地，
 * 全站 19 个用 UiDataTable 的视图都没有行分隔线（2026-09-29 定位）。
 *
 * 这里同时锁两层：PT 配置的段名，以及渲染出的 `<tr>` 真的拿到了那些类。
 * 挂载必须按生产配置（unstyled + PT）——默认模式渲染出的 `p-*` 类名生产里不存在。
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import UiDataTable from '@/components/ui/UiDataTable.vue'

const ROWS = [
  { id: 1, name: '甲' },
  { id: 2, name: '乙' },
]
const COLS = [{ field: 'name', header: '名称' }]

function mountTable(selection?: typeof ROWS | null) {
  return mount(UiDataTable, {
    props: { data: ROWS, columns: COLS, ...(selection ? { selection } : {}) },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

describe('PrimeVue DataTable 行样式', () => {
  it('行分隔线随 bodyRow（tr 本体）生效，而不是写在死键 row 上', () => {
    const tr = mountTable().find('tbody tr')
    // 按 class token 精确比对：`border-border` 是 `border-border-light` 的子串，
    // 用 toContain 直接搜字符串会让旧值也通过（假绿），故先切分。
    const classes = (tr.attributes('class') ?? '').split(/\s+/)

    expect(classes).toContain('border-b')
    // 2026-09-30：行线从 border-border-light(#f0f2f5) 换成 border-border(#e4e7ed)。
    // 原色对白底对比度仅 1.122:1，行与行之间看不出分界；换成与表头下边线/表格外框同色后为 1.239:1，
    // 全表网格线统一成一个色调（用户以对比稿选定）。断言跟到新色名，防止日后被悄悄改回浅色。
    expect(classes).toContain('border-border')
    expect(classes).not.toContain('border-border-light')
  })

  it('行 hover 同样落在 tr 上', () => {
    const tr = mountTable().find('tbody tr')

    expect(tr.attributes('class')).toContain('hover:bg-slate-50')
  })

  it('PT 配置用的是 bodyRow 段名（row 段对表格行无效）', () => {
    const datatable = plushCutePT.datatable
    if (typeof datatable !== 'object' || datatable === null) {
      throw new Error('datatable PT 应为静态对象')
    }

    expect(datatable.bodyRow).toBeDefined()
  })

  it('选中行仍然高亮（bodyRow 的 context.selected 分支没丢）', () => {
    const tr = mountTable([ROWS[0]!]).findAll('tbody tr')[0]

    expect(tr?.attributes('class')).toContain('bg-primary-50')
  })
})

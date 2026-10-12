import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import BackupRecordTable, { type BackupRecordRow } from '@/components/backup/BackupRecordTable.vue'

/**
 * /backup 审计（high）：记录表**双重分页**。
 *
 * 父组件已经按服务端分页取回第 page 页（`/backup/records?page=&page_size=`），
 * 组件内却又 `filtered.slice((page-1)*pageSize, ...)` 切了一次：
 * 第 2 页时 rows 只有 pageSize 条，而 start 已 ≥ pageSize ⇒ 整页切空。
 * 表现为"翻到第 2 页什么都没有"，且连"暂无备份记录"都不显示
 * （rows.length 非 0，空态行也不渲染）。
 */
let seq = 0
function row(filename: string, extra: Partial<BackupRecordRow> = {}): BackupRecordRow {
  seq += 1
  return { id: seq, filename, type: 'full', status: 'success', size: 1024, ...extra }
}

function mountTable(rows: BackupRecordRow[], page = 1, total = rows.length) {
  return mount(BackupRecordTable, {
    props: { rows, total, page, pageSize: 20, onPageChange: () => {} },
  })
}

describe('BackupRecordTable 分页', () => {
  it('第 1 页渲染服务端返回的行', () => {
    const wrapper = mountTable([row('a.zip'), row('b.zip')])

    expect(wrapper.text()).toContain('a.zip')
    expect(wrapper.text()).toContain('b.zip')
  })

  it('第 2 页仍然渲染服务端返回的行（不得再切一次）', () => {
    const wrapper = mountTable([row('p2-a.zip'), row('p2-b.zip')], 2, 42)

    expect(wrapper.text()).toContain('p2-a.zip')
    expect(wrapper.text()).toContain('p2-b.zip')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  })

  it('第 3 页同样不为空', () => {
    const wrapper = mountTable([row('p3-only.zip')], 3, 61)

    expect(wrapper.text()).toContain('p3-only.zip')
  })

  it('空页给出空态文案而不是一片空白', () => {
    const wrapper = mountTable([], 1, 0)

    expect(wrapper.text()).toContain('暂无备份记录')
  })

  it('筛选只作用于当前页（服务端无筛选入口）', async () => {
    const wrapper = mountTable([row('full.zip', { type: 'full' }), row('restore.zip', { type: 'restore' })], 2, 42)

    await wrapper.findAll('select')[0]!.setValue('full')

    expect(wrapper.text()).toContain('full.zip')
    expect(wrapper.text()).not.toContain('restore.zip')
  })

  it('翻页按钮按服务端 total 计算页数并派发事件', async () => {
    const onPageChange = vi.fn()
    const wrapper = mount(BackupRecordTable, {
      props: { rows: [row('a.zip')], total: 42, page: 2, pageSize: 20, onPageChange },
    })

    expect(wrapper.text()).toContain('第 2 / 3 页')

    const buttons = wrapper.findAll('.brt-page')
    expect(buttons).toHaveLength(2)
    await buttons[0]!.trigger('click')
    await buttons[1]!.trigger('click')

    expect(wrapper.emitted('page-change')).toEqual([[1], [3]])
  })
})

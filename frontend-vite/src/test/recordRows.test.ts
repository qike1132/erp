/**
 * useReportRowActions 导出的纯函数测试。
 *
 * 本文件前身是 recordRows.test.ts（记录列表多 SKU 行摊平，flattenRecordRows）。
 * 该主题函数已随 2026-10-06 记录查询 tab 收敛至 /report 而删除；本文件承接
 * /report 同层新主题：聚合行还原的两块纯逻辑 —— parseGroupNos（组内单号解析）
 * 与 matchRecordsByNos（按单号精确匹配 + missing 清单）。
 */
import { describe, expect, it } from 'vitest'
import { parseGroupNos, matchRecordsByNos } from '@/views/report/composables/useReportRowActions'
import type { UnifiedRecord } from '@/api/order'

/** 后端 _string_agg(..., ', ') 的聚合单号串（report_service.py:142,319） */
const AGG_NOS = 'PO-20260930-0012, PO-20260930-0013'

function record(id: number, orderNo: string): UnifiedRecord {
  return {
    id,
    record_type: 'order',
    order_no: orderNo,
    customer: 'MINISO国际',
    order_date: '2026-09-30 10:00',
    status: '待备货',
    product: { id: 1, name: '鲨鱼毛绒公仔', barcode: '690123', image: '' },
    quantity: 10000,
    deduct_quantity: 0,
    factories: ['东莞'],
    items: [],
  }
}

describe('parseGroupNos（组内单号解析）', () => {
  it('按逗号切分并 trim（后端以 ", " 连接）', () => {
    expect(parseGroupNos(AGG_NOS)).toEqual(['PO-20260930-0012', 'PO-20260930-0013'])
  })

  it('备货聚合串同样解析（stockin_nos）', () => {
    expect(parseGroupNos('BH-20260929-0001,BH-20260929-0002'))
      .toEqual(['BH-20260929-0001', 'BH-20260929-0002'])
  })

  it('去空：尾逗号与连续逗号不产生空串项', () => {
    expect(parseGroupNos('A-1,, A-2, ,')).toEqual(['A-1', 'A-2'])
  })

  it('空串/纯空白 → 空数组', () => {
    expect(parseGroupNos('')).toEqual([])
    expect(parseGroupNos('   ')).toEqual([])
  })
})

describe('matchRecordsByNos（单号精确匹配）', () => {
  const rows = [record(1, 'PO-20260930-0012'), record(2, 'PO-20260930-0013'), record(3, 'PO-20260930-0014')]

  it('命中行按组内单号顺序输出', () => {
    const { matched, missing } = matchRecordsByNos(rows, ['PO-20260930-0013', 'PO-20260930-0012'])

    expect(matched.map((r) => r.order_no)).toEqual(['PO-20260930-0013', 'PO-20260930-0012'])
    expect(missing).toEqual([])
  })

  it('漏单进 missing 清单（供逐单号补查兜底）', () => {
    const { matched, missing } = matchRecordsByNos(rows, ['PO-20260930-0012', 'PO-99999999-0001'])

    expect(matched.map((r) => r.id)).toEqual([1])
    expect(missing).toEqual(['PO-99999999-0001'])
  })

  it('全部缺失：matched 为空、missing 保留原始顺序', () => {
    const { matched, missing } = matchRecordsByNos(rows, ['X-2', 'X-1'])

    expect(matched).toEqual([])
    expect(missing).toEqual(['X-2', 'X-1'])
  })

  it('还原查询重复单号时只取第一行（幂等）', () => {
    const duplicated = [record(1, 'PO-20260930-0012'), record(99, 'PO-20260930-0012')]
    const { matched } = matchRecordsByNos(duplicated, ['PO-20260930-0012'])

    expect(matched.map((r) => r.id)).toEqual([1])
  })
})

import { describe, it, expect } from 'vitest'
// 结构锁：迁移到手写层 → 生成层派生别名后，「字段清单没变、必填口径没松」这两件事
// 必须由编译期断言兜住。Equal<> 赋给 true 一旦类型退化就编译报错（TS2322），
// 指令行一旦不再咬住也报错（TS2578）——两条路都把「静默变松」变成红。
import type { BatchQueryListResponse } from '@/api/batch'
import type { BackupScheduleTask, BatchQueryItem } from '@/types'
import type { BatchQueryListResponse as GenBatchQueryListResponse } from '@/types/api'

type Equal<X, Y> =
  (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? true : false

describe('DTO 派生别名的形状锁', () => {
  it('BatchQueryListResponse：键集沿用生成层，data 元素是加强后的 BatchQueryItem', () => {
    const keysMatchGen: Equal<keyof BatchQueryListResponse, keyof GenBatchQueryListResponse> = true
    const dataIsStrengthened: Equal<BatchQueryListResponse['data'], BatchQueryItem[]> = true
    expect(keysMatchGen).toBe(true)
    expect(dataIsStrengthened).toBe(true)

    // @ts-expect-error 生成层 data 可选，派生后必填
    const withoutData: BatchQueryListResponse = { success: true, total: 0, page: 1, per_page: 20 }
    void withoutData
  })

  it('BackupScheduleTask：只留前端消费的 6 个键，enabled 必填、last_* 可缺省', () => {
    const keys: Equal<
      keyof BackupScheduleTask,
      'name' | 'task' | 'schedule' | 'enabled' | 'last_run' | 'last_status'
    > = true
    expect(keys).toBe(true)

    // @ts-expect-error enabled 断言为必填
    const withoutEnabled: BackupScheduleTask = { name: 'n', task: 't', schedule: 's', last_run: null, last_status: null }
    void withoutEnabled

    const optionalKept: BackupScheduleTask = { name: 'n', task: 't', schedule: 's', enabled: true }
    expect(optionalKept.last_run).toBeUndefined()
  })
})

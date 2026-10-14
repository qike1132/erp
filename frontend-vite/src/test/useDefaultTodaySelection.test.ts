// A3 默认选中今天 —— useDefaultTodaySelection composable 的行为锁定。
// 纯 TS + Vue reactivity，不挂 PrimeVue。用 fake timers 钉住「今天」= 2026-10-14。
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref, computed, nextTick } from 'vue'
import { useDefaultTodaySelection } from '@/views/purchase-plan/composables/useDefaultTodaySelection'
import type { Row } from '@/views/purchase-plan/components/types'

/** 满足 Row 类型的最小行，本任务只用 date 字段 */
function row(date: string): Row {
  return {
    date,
    _dayNum: 0,
    _weekday: '',
    customerCount: 0,
    planCount: 0,
    totalQty: 0,
    _isPeak: false,
    _producedCount: 0,
    _pendingCount: 0,
    _producedPct: 0,
    customerNames: [],
    _fullDate: date,
  }
}

describe('useDefaultTodaySelection', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-14T10:00:00'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('数据到达且今天在本月且有排产 → 选中今天', async () => {
    const y = ref(2026)
    const m = ref(10)
    const factory = ref('')
    const rows = ref<Row[]>([])
    const sel = ref('')

    useDefaultTodaySelection({
      y,
      m,
      factory,
      rows: computed(() => rows.value),
      sel,
    })

    expect(sel.value).toBe('')

    rows.value = [row('2026-10-14'), row('2026-10-05')]
    await nextTick()

    expect(sel.value).toBe('2026-10-14')
  })

  it('今天无排产 → 不选中', async () => {
    const y = ref(2026)
    const m = ref(10)
    const factory = ref('')
    const rows = ref<Row[]>([row('2026-10-05')])
    const sel = ref('')

    useDefaultTodaySelection({
      y,
      m,
      factory,
      rows: computed(() => rows.value),
      sel,
    })
    await nextTick()

    expect(sel.value).toBe('')
  })

  it('今天不在当前月份 → 不选中', async () => {
    const y = ref(2026)
    const m = ref(9)
    const factory = ref('')
    const rows = ref<Row[]>([row('2026-10-14')])
    const sel = ref('')

    useDefaultTodaySelection({
      y,
      m,
      factory,
      rows: computed(() => rows.value),
      sel,
    })
    await nextTick()

    expect(sel.value).toBe('')
  })

  it('用户手动改选后，数据刷新不再覆盖', async () => {
    const y = ref(2026)
    const m = ref(10)
    const factory = ref('')
    const rows = ref<Row[]>([row('2026-10-14'), row('2026-10-05')])
    const sel = ref('')

    useDefaultTodaySelection({
      y,
      m,
      factory,
      rows: computed(() => rows.value),
      sel,
    })
    await nextTick()
    expect(sel.value).toBe('2026-10-14')

    sel.value = '2026-10-05'
    await nextTick()

    rows.value = [...rows.value, row('2026-10-20')]
    await nextTick()

    expect(sel.value).toBe('2026-10-05')
  })

  it('换月后重新落到新月的今天', async () => {
    const y = ref(2026)
    const m = ref(9)
    const factory = ref('')
    const rows = ref<Row[]>([row('2026-10-14')])
    const sel = ref('')

    useDefaultTodaySelection({
      y,
      m,
      factory,
      rows: computed(() => rows.value),
      sel,
    })
    await nextTick()
    expect(sel.value).toBe('')

    m.value = 10
    await nextTick()

    expect(sel.value).toBe('2026-10-14')
  })
})

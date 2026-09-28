import { describe, expect, it } from 'vitest'
import { plushCutePT } from '@/styles/primevue-pt'

describe('PrimeVue AutoComplete pass-through', () => {
  it('keeps the loading icon out of the input flow', () => {
    // PT 类型允许「对象 | 函数」联合；本项目的 autocomplete PT 是静态对象，
    // 用 typeof 收窄类型并同时锁住这一约定（若被改成函数式 PT 会显式失败而非静默通过）。
    const autocomplete = plushCutePT.autocomplete
    if (typeof autocomplete !== 'object' || autocomplete === null) {
      throw new Error('autocomplete PT 应为静态对象，而非函数式/缺省 PT')
    }

    expect(autocomplete.root).toContain('relative')
    expect(autocomplete.loader).toContain('absolute')
  })
})

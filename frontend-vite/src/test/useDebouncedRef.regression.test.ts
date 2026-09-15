import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { computed, ref, reactive, nextTick } from 'vue'
import { useDebouncedRef, useDebouncedRefReactive } from '@/composables/useDebouncedRef'

/**
 * 回归测试：useDebouncedRef 必须**持续跟随**传入的 Ref/ComputedRef
 *
 * 背景（2026-09-14 修复）：原实现 `refDebounced(ref(source.value), delay)`
 * 对传入值取快照，导致 ComputedRef 的变化永远不传播。
 * 真实影响 src/views/stock/InventoryTab.vue:100 的产品筛选恒为空 →
 * 库存页按产品筛选完全失效。本文件锁定修复后的契约。
 *
 * ⚠️ 测试要点：VueUse 的 refDebounced 内部用 watch + 定时器。
 * watch 回调在 **微任务**（nextTick）中执行，之后才启动定时器；
 * 因此在 fake timers 下必须先 `await nextTick()`，再推进虚拟时间，
 * 否则定时器尚未被注册，advanceTimersByTime 不可能触发更新。
 */
describe('useDebouncedRef', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  /** 推进虚拟时间前先让 Vue 的 watcher 结算（微任务） */
  async function flushAndAdvance(ms: number) {
    await nextTick()
    vi.advanceTimersByTime(ms)
  }

  it('传入 ComputedRef：变化经 debounce 后反映（原缺陷场景）', async () => {
    const filters = ref({ product: '' })
    const source = computed(() => filters.value.product)

    const debounced = useDebouncedRef(source, 300)
    expect(debounced.value).toBe('')

    filters.value = { product: '螺丝' }
    await flushAndAdvance(300)

    // 修复前此处恒为 ''（ComputedRef 变化永不传播）
    expect(debounced.value).toBe('螺丝')
  })

  it('传入普通 ref：延迟到期后更新（不再永不更新）', async () => {
    const source = ref('init')
    const debounced = useDebouncedRef(source, 300)

    source.value = 'changed'
    await nextTick()
    // 到期前保持旧值
    vi.advanceTimersByTime(299)
    expect(debounced.value).toBe('init')

    vi.advanceTimersByTime(1)
    expect(debounced.value).toBe('changed')
  })

  it('连续变化只取最终值（debounce 语义）', async () => {
    const source = ref('a')
    const debounced = useDebouncedRef(source, 300)

    source.value = 'b'
    await nextTick()
    vi.advanceTimersByTime(100)
    source.value = 'c'
    await nextTick()
    vi.advanceTimersByTime(100)
    source.value = 'd'
    await flushAndAdvance(300)

    expect(debounced.value).toBe('d')
  })

  it('非 ref 普通对象降级为快照语义（不抛异常，DEV 下告警）', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const source = { value: 'snapshot' }
    const debounced = useDebouncedRef(source, 300)

    expect(debounced.value).toBe('snapshot')
    source.value = 'ignored'
    vi.advanceTimersByTime(300)
    expect(debounced.value).toBe('snapshot')
    warn.mockRestore()
  })

  it('遵循自定义延迟', async () => {
    const source = ref(1)
    const debounced = useDebouncedRef(source, 500)
    source.value = 2
    await nextTick()

    vi.advanceTimersByTime(499)
    expect(debounced.value).toBe(1)
    vi.advanceTimersByTime(1)
    expect(debounced.value).toBe(2)
  })
})

describe('useDebouncedRefReactive', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('普通对象无法被 watch 追踪，仍退化为快照（Vue 响应式语义所限）', async () => {
    const source = { value: 'init' }
    const debounced = useDebouncedRefReactive(source, 300)

    source.value = 'changed'
    await nextTick()
    vi.advanceTimersByTime(300)
    // 非响应式对象属性变化 Vue 无法感知 —— 需要跟随请改用 ref/reactive
    expect(debounced.value).toBe('init')
  })

  it('reactive 对象的属性可持续跟随', async () => {
    const state = reactive({ value: 'init' })
    const debounced = useDebouncedRefReactive(state, 300)

    state.value = 'changed'
    await nextTick()
    vi.advanceTimersByTime(300)
    expect(debounced.value).toBe('changed')
  })

  it('ComputedRef 同样跟随', async () => {
    const base = ref('x')
    const source = computed(() => base.value)
    const debounced = useDebouncedRefReactive(source, 300)

    base.value = 'y'
    await nextTick()
    vi.advanceTimersByTime(300)
    expect(debounced.value).toBe('y')
  })
})

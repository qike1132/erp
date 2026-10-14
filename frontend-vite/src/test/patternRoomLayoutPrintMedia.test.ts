import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { defineComponent, h, nextTick, watch } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { usePatternRoomLayout } from '@/views/pattern-room/composables/usePatternRoomLayout'

/**
 * 打样间响应式布局 × 打印媒体回归测试
 *
 * 线上 BUG：在「进行中」列表选中非首个 SKU → 点「打印打样单」→ 在打印流程中点
 * 「取消」→ 左侧列表跳回第一个 SKU。
 *
 * 根因：打印期间文档媒体类型变为 print，Chrome 按纸张宽度（A4 约 794px）重新求值
 * `(max-width: 1023px)` 并派发 change，isNarrow 翻转为 true；PatternRoomSplitBody
 * 用 `v-if="!isNarrow"` 卸载整个左侧列表（CustomerGroupList / CustomerProjectArea /
 * VirtualList），打印结束重新挂载后，选中分组、分页、滚动位置全部回到初始值。
 *
 * 守住的不变量：媒体类型为 print 时 isNarrow 必须保持 false（屏幕媒体下的窄屏
 * 抽屉切换不受影响）。
 */

type MediaCtx = { media: 'screen' | 'print'; width: number }

/** 极简媒体查询求值：支持 screen/print 前缀 + 单个 (max-width: Npx) */
function evaluate(query: string, ctx: MediaCtx): boolean {
  for (const raw of query.split(' and ')) {
    const part = raw.trim()
    if (part === 'screen') {
      if (ctx.media !== 'screen') return false
      continue
    }
    if (part === 'print') {
      if (ctx.media !== 'print') return false
      continue
    }
    const m = part.match(/^\(max-width:\s*(\d+)px\)$/)
    if (!m) throw new Error(`测试桩不支持的媒体特性: ${part}`)
    if (ctx.width > Number(m[1])) return false
  }
  return true
}

class FakeMediaQueryList {
  readonly listeners = new Set<(e: { matches: boolean }) => void>()
  constructor(
    readonly query: string,
    private readonly ctx: () => MediaCtx,
  ) {}
  get matches(): boolean {
    return evaluate(this.query, this.ctx())
  }
  addEventListener(_type: 'change', cb: (e: { matches: boolean }) => void): void {
    this.listeners.add(cb)
  }
  removeEventListener(_type: 'change', cb: (e: { matches: boolean }) => void): void {
    this.listeners.delete(cb)
  }
  /** 模拟浏览器重新求值后派发 change */
  dispatch(): void {
    const matches = this.matches
    for (const cb of [...this.listeners]) cb({ matches })
  }
}

let ctx: MediaCtx = { media: 'screen', width: 1440 }
let queries: FakeMediaQueryList[] = []
const originalMatchMedia = window.matchMedia

function installMatchMedia(): void {
  queries = []
  window.matchMedia = ((query: string) => {
    const mql = new FakeMediaQueryList(query, () => ctx)
    queries.push(mql)
    return mql as unknown as MediaQueryList
  }) as typeof window.matchMedia
}

/** 切换媒体上下文（等价于浏览器进入/退出打印渲染） */
function setMedia(next: MediaCtx): void {
  ctx = next
  for (const q of queries) q.dispatch()
}

/** isNarrow 出现过的每个值（watch 只记录变化；初始值由挂载断言覆盖） */
let narrowSeen: boolean[] = []

const Probe = defineComponent({
  setup() {
    const { isNarrow } = usePatternRoomLayout()
    watch(isNarrow, (v) => narrowSeen.push(v))
    return () => h('span', { 'data-narrow': String(isNarrow.value) })
  },
})

let wrapper: VueWrapper | null = null

/** 挂载探针；onMounted 在微任务中执行，必须 await nextTick 后再断言 */
async function mountProbe(): Promise<void> {
  narrowSeen = []
  wrapper = mount(Probe)
  await nextTick()
}

function isNarrowRendered(): boolean {
  return wrapper!.find('span').attributes('data-narrow') === 'true'
}

describe('usePatternRoomLayout × 打印媒体', () => {
  beforeEach(() => {
    ctx = { media: 'screen', width: 1440 }
    installMatchMedia()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    window.matchMedia = originalMatchMedia
  })

  it('屏幕宽屏：isNarrow 为 false', async () => {
    await mountProbe()

    expect(isNarrowRendered()).toBe(false)
  })

  it('屏幕窄屏（< 1024px）：isNarrow 为 true，抽屉布局仍生效', async () => {
    ctx = { media: 'screen', width: 800 }
    await mountProbe()

    expect(isNarrowRendered()).toBe(true)
  })

  it('打印渲染期间（纸张宽度 794px）isNarrow 不得翻转', async () => {
    await mountProbe()

    setMedia({ media: 'print', width: 794 })
    await nextTick()

    expect(isNarrowRendered()).toBe(false)
  })

  it('打印 → 回到屏幕全程 isNarrow 从未翻真（不产生卸载/重挂载）', async () => {
    await mountProbe()

    setMedia({ media: 'print', width: 794 })
    await nextTick()
    // 打印期间就要查一次：只看末态会漏掉「中途翻真又复位」的旧代码行为
    expect(isNarrowRendered()).toBe(false)
    setMedia({ media: 'screen', width: 1440 })
    await nextTick()

    expect(isNarrowRendered()).toBe(false)
    // watch 全程捕获 isNarrow 的每次取值，中途任何一次翻真都会留痕
    expect(narrowSeen).not.toContain(true)
  })

  it('屏幕下从宽屏缩到窄屏再恢复，isNarrow 跟随变化', async () => {
    await mountProbe()

    setMedia({ media: 'screen', width: 800 })
    await nextTick()
    expect(isNarrowRendered()).toBe(true)

    setMedia({ media: 'screen', width: 1440 })
    await nextTick()
    expect(isNarrowRendered()).toBe(false)
  })
})

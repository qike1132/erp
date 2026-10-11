<template>
  <div
    ref="containerRef"
    class="virtual-list-container"
    role="list"
    :style="{ height: `${containerHeight}px` }"
    @scroll.passive="onScrollPassive"
  >
    <div
      class="virtual-list-phantom"
      :style="{ height: `${totalHeight}px` }"
    />
    <div
      class="virtual-list-content"
      :style="{ transform: `translateY(${offsetY}px)` }"
    >
      <div
        v-for="item in visibleItems"
        :key="getItemKey(item)"
        :ref="el => setItemRef(el, item.index)"
        class="virtual-list-item"
        role="listitem"
        :style="getItemStyle(item.index)"
      >
        <slot :item="item.raw" :index="item.index" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts" generic="T">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'

interface VirtualItem<T> {
  raw: T
  index: number
}

const props = withDefaults(defineProps<{
  items: T[]
  itemHeight: number
  containerHeight: number
  buffer?: number
  itemKey?: (item: T, index: number) => string | number
  dynamicHeight?: boolean
  estimatedHeight?: number
}>(), {
  buffer: 10,
  dynamicHeight: false,
  estimatedHeight: 48,
})

const emit = defineEmits<{
  visibleChange: [startIndex: number, endIndex: number]
}>()

const containerRef = ref<HTMLElement | null>(null)
const scrollTop = ref(0)

const bufferCount = computed(() => props.buffer ?? 10)
const estimatedH = computed(() => props.dynamicHeight ? props.estimatedHeight : props.itemHeight)

// Non-reactive height cache — avoids triggering full prefix-sum recomputation on every measurement.
// _heightVersion bumps only when a measured height actually changes, driving _prefixSums recompute.
const _heightMap = new Map<number, number>()
const _itemCountRef = ref(0)
const _heightVersion = ref(0)
const itemRefs: Map<number, HTMLElement> = new Map()
let itemRefGeneration = 0

function setItemRef(el: unknown, index: number) {
  if (el instanceof HTMLElement) {
    itemRefs.set(index, el)
  } else {
    itemRefs.delete(index)
  }
}

/**
 * 取「承载内容自然高度」的元素。
 *
 * 变高模式下 `.virtual-list-item` 自身被赋予 inline `min-height`（见 getItemStyle），
 * 若直接量它，量到的会是 `max(内容高, 缓存高)` —— 一旦某行曾展开（缓存变大），
 * 收起后会被 `min-height` 顶住、永远量不到缩小后的真实高（RC-4 的自相矛盾测量）。
 * 因此优先量首个元素子节点（即插槽内容根节点，其高度由内容决定、不受本项
 * `min-height` 约束），拿不到时退化为量本项自身。
 */
function resolveMeasureTarget(el: HTMLElement): HTMLElement {
  const first = el.firstElementChild
  return first instanceof HTMLElement ? first : el
}

function measureItems() {
  if (!props.dynamicHeight) return
  const currentGen = ++itemRefGeneration
  let changed = false
  for (const [idx, el] of itemRefs) {
    if (itemRefGeneration !== currentGen) return
    const h = resolveMeasureTarget(el).getBoundingClientRect().height
    // h <= 0 视为不可信测量（display:none / 未布局），保留旧值不覆盖
    if (h > 0 && _heightMap.get(idx) !== h) {
      _heightMap.set(idx, h)
      changed = true
    }
  }
  itemRefs.clear()
  // 仅在实际高度变化时才触发前缀和重算，高度稳定后零开销
  if (changed) _heightVersion.value++
}

/**
 * 作废指定项的高度缓存并立即重测（行内展开/收起等局部内容变化时由父组件调用）。
 * 不清除则 `min-height` 会一直顶住旧高度，导致收起的行收不回去。
 */
function remeasureItem(index: number) {
  if (!props.dynamicHeight) return
  if (_heightMap.delete(index)) _heightVersion.value++
}

// （原 _getItemHeight 已删：与 _prefixSums 内联逻辑重复的死代码，评审 2026-10-11）

const _prefixSums = computed(() => {
  if (!props.dynamicHeight) return null
  // Recompute when item count changes OR when a measured height actually changes.
  // _heightMap is non-reactive; _heightVersion bumps on real changes to trigger recompute.
  void _itemCountRef.value
  void _heightVersion.value
  const n = props.items.length
  const sums = new Float64Array(n + 1)
  let acc = 0
  for (let i = 0; i < n; i++) {
    acc += _heightMap.get(i) || estimatedH.value
    sums[i + 1] = acc
  }
  return sums
})

function getPosition(index: number): number {
  if (!props.dynamicHeight) return index * props.itemHeight
  return _prefixSums.value?.[index] ?? index * estimatedH.value
}

function findStartIndex(scrollPos: number): number {
  if (scrollPos <= 0) return 0
  if (!props.dynamicHeight) return Math.floor(scrollPos / props.itemHeight)
  if (_heightMap.size === 0) return Math.floor(scrollPos / estimatedH.value)
  let lo = 0, hi = props.items.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (getPosition(mid) < scrollPos) lo = mid + 1
    else hi = mid - 1
  }
  return Math.max(0, lo - 1)
}

const totalHeight = computed(() => {
  if (!props.dynamicHeight) return props.items.length * props.itemHeight
  if (_prefixSums.value) return _prefixSums.value[props.items.length]!
  return props.items.length * estimatedH.value
})

const startIndex = computed(() => {
  const idx = findStartIndex(scrollTop.value)
  return Math.max(0, idx - bufferCount.value)
})

const visibleCount = computed(() => {
  const h = props.dynamicHeight ? estimatedH.value : props.itemHeight
  if (h <= 0 || props.containerHeight <= 0) return bufferCount.value * 2
  return Math.ceil(props.containerHeight / h) + bufferCount.value * 2
})

const endIndex = computed(() => {
  return Math.min(props.items.length, startIndex.value + visibleCount.value)
})

const visibleItems = computed<VirtualItem<T>[]>(() => {
  const result: VirtualItem<T>[] = []
  for (let i = startIndex.value; i < endIndex.value; i++) {
    if (i < props.items.length) {
      result.push({ raw: props.items[i]!, index: i })
    }
  }
  return result
})

const offsetY = computed(() => {
  if (!props.dynamicHeight) return startIndex.value * props.itemHeight
  return getPosition(startIndex.value)
})

function getItemStyle(index: number) {
  if (!props.dynamicHeight) {
    return { height: `${props.itemHeight}px` }
  }
  const h = _heightMap.get(index) || estimatedH.value
  // 变高模式改用 min-height：既为未测量项提供稳定占位，又允许内容自然生长，
  // 使 measureItems 能学到内容真实高度（RC-4 硬前置修复）
  return { minHeight: `${h}px` }
}

function getItemKey(item: VirtualItem<T>): string | number {
  if (props.itemKey) {
    return props.itemKey(item.raw, item.index)
  }
  return item.index
}

let rafId: number | null = null
function onScrollPassive() {
  if (rafId !== null) return
  rafId = requestAnimationFrame(() => {
    if (containerRef.value) {
      scrollTop.value = containerRef.value.scrollTop
    }
    if (props.dynamicHeight) {
      measureItems()
    }
    rafId = null
  })
}

function scrollToIndex(index: number) {
  if (!containerRef.value) return
  if (props.dynamicHeight) {
    containerRef.value.scrollTop = getPosition(index)
  } else {
    containerRef.value.scrollTop = index * props.itemHeight
  }
}

function scrollToTop() {
  if (containerRef.value) {
    containerRef.value.scrollTop = 0
  }
}

function scrollToBottom() {
  if (containerRef.value) {
    containerRef.value.scrollTop = totalHeight.value ?? 0
  }
}

watch(() => props.items.length, (newLen, oldLen) => {
  if (newLen !== oldLen) {
    _itemCountRef.value = newLen
    if (scrollTop.value > (totalHeight.value ?? 0)) {
      nextTick(() => scrollToTop())
    }
  }
})

watch([startIndex, endIndex], ([s, e]) => {
  emit('visibleChange', s, e)
})

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  // 仅动态高度模式需要 ResizeObserver（触发 measureItems + 同步 scrollTop）
  // 固定高度模式由父级 useVirtualAreaMeasure 监听容器尺寸变化，此处不再重复监听
  if (props.dynamicHeight && containerRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      if (containerRef.value) {
        scrollTop.value = containerRef.value.scrollTop
      }
      measureItems()
    })
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  if (rafId !== null) cancelAnimationFrame(rafId)
  itemRefs.clear()
})

defineExpose({
  scrollToIndex,
  scrollToTop,
  scrollToBottom,
  measureItems,
  remeasureItem,
})
</script>

<style scoped>
.virtual-list-container {
  position: relative;
  overflow-y: auto;
  overflow-x: hidden;
  will-change: scroll-position;
}
.virtual-list-phantom {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: -1;
}
.virtual-list-content {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  will-change: transform;
}
.virtual-list-item {
  box-sizing: border-box;
}
</style>

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
        class="virtual-list-item"
        role="listitem"
        :ref="el => setItemRef(el, item.index)"
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
// Keyed by itemKey (falls back to index when itemKey is absent) so stale heights from a previous
// page's items are never reused for a different row at the same index.
// _heightVersion bumps only when a measured height actually changes, driving _prefixSums recompute.
const _heightMap = new Map<string | number, number>()
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

/** index → 缓存键：优先 itemKey(raw)，无 itemKey 或越界时回退 index */
function keyOfIndex(index: number): string | number {
  const raw = props.items[index]
  if (raw === undefined) return index
  return props.itemKey ? props.itemKey(raw, index) : index
}

function measureItems() {
  if (!props.dynamicHeight) return
  const currentGen = ++itemRefGeneration
  let changed = false
  for (const [idx, el] of itemRefs) {
    if (itemRefGeneration !== currentGen) return
    const h = el.getBoundingClientRect().height
    const key = keyOfIndex(idx)
    if (_heightMap.get(key) !== h) {
      _heightMap.set(key, h)
      changed = true
    }
  }
  itemRefs.clear()
  // 仅在实际高度变化时才触发前缀和重算，高度稳定后零开销
  if (changed) _heightVersion.value++
}

function _getItemHeight(index: number): number {
  if (!props.dynamicHeight) return props.itemHeight
  return _heightMap.get(keyOfIndex(index)) || estimatedH.value
}

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
    acc += _heightMap.get(keyOfIndex(i)) || estimatedH.value
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
  const h = _heightMap.get(keyOfIndex(index)) || estimatedH.value
  return { height: `${h}px` }
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

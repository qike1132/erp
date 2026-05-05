<template>
  <div
    ref="containerRef"
    class="virtual-list-container"
    :style="{ height: `${containerHeight}px` }"
    @scroll="handleScroll"
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
        :style="itemStyle"
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

const props = defineProps<{
  items: T[]
  itemHeight: number
  containerHeight: number
  buffer?: number
  itemKey?: (item: T, index: number) => string | number
}>()

const containerRef = ref<HTMLElement | null>(null)
const scrollTop = ref(0)

const bufferCount = computed(() => props.buffer ?? 5)
const totalHeight = computed(() => props.items.length * props.itemHeight)

const startIndex = computed(() => {
  const idx = Math.floor(scrollTop.value / props.itemHeight)
  return Math.max(0, idx - bufferCount.value)
})

const visibleCount = computed(() => {
  return Math.ceil(props.containerHeight / props.itemHeight) + bufferCount.value * 2
})

const endIndex = computed(() => {
  return Math.min(props.items.length, startIndex.value + visibleCount.value)
})

const visibleItems = computed<VirtualItem<T>[]>(() => {
  const result: VirtualItem<T>[] = []
  for (let i = startIndex.value; i < endIndex.value; i++) {
    if (i < props.items.length) {
      result.push({ raw: props.items[i], index: i })
    }
  }
  return result
})

const offsetY = computed(() => startIndex.value * props.itemHeight)

function getItemKey(item: VirtualItem<T>): string | number {
  if (props.itemKey) {
    return props.itemKey(item.raw, item.index)
  }
  return item.index
}

const itemStyle = computed(() => ({
  height: `${props.itemHeight}px`,
}))

function handleScroll() {
  if (containerRef.value) {
    scrollTop.value = containerRef.value.scrollTop
  }
}

function scrollToIndex(index: number) {
  if (containerRef.value) {
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
    containerRef.value.scrollTop = totalHeight.value
  }
}

// 监听 items 变化，自动滚动到顶部
watch(() => props.items.length, (newLen, oldLen) => {
  if (newLen !== oldLen && scrollTop.value > totalHeight.value) {
    nextTick(() => {
      scrollToTop()
    })
  }
})

// ResizeObserver 监听容器高度变化
let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (containerRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      handleScroll()
    })
    resizeObserver.observe(containerRef.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
})

defineExpose({
  scrollToIndex,
  scrollToTop,
  scrollToBottom,
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

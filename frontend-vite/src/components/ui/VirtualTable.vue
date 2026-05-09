<template>
  <div ref="containerRef" class="vt-container" :style="{ height: `${containerHeight}px` }">
    <div v-if="columns.length" class="vt-header">
      <div v-for="col in columns" :key="col.key" class="vt-th"
        :style="{ width: col.width ? `${col.width}px` : 'auto', minWidth: col.minWidth ? `${col.minWidth}px` : '80px' }"
        @click="col.sortable && handleSort(col)">
        <span>{{ col.title }}</span>
        <span v-if="sortKey===col.key" class="sort-ind">{{ sortOrder==='asc'?'↑':'↓' }}</span>
      </div>
    </div>
    <div class="vt-body" :style="{ height: `${containerHeight - headerHeight}px` }" @scroll.passive="onScroll">
      <div class="vt-phantom" :style="{ height: `${totalHeight}px` }" />
      <div class="vt-content" :style="{ transform: `translateY(${offsetY}px)` }">
        <div v-for="item in visibleItems" :key="itemKey(item)" class="vt-row"
          :style="getItemStyle(item.index)" @click="$emit('rowClick', item.raw, item.index)">
          <div v-for="col in columns" :key="col.key" class="vt-td"
            :style="{ width: col.width ? `${col.width}px` : 'auto', minWidth: col.minWidth ? `${col.minWidth}px` : '80px' }">
            <slot :name="col.key" :item="item.raw" :index="item.index" :value="item.raw[col.key]">
              {{ item.raw[col.key] }}
            </slot>
          </div>
        </div>
      </div>
    </div>
    <div v-if="loading" class="vt-loading"><slot name="loading">加载中...</slot></div>
  </div>
</template>

<script setup lang="ts" generic="T extends Record<string, any>">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'

interface ColDef { key: string; title: string; width?: number; minWidth?: number; sortable?: boolean }

const props = withDefaults(defineProps<{
  items: T[]; columns: ColDef[]; itemHeight: number; containerHeight: number
  headerHeight?: number; buffer?: number; itemKeyFn?: (item: T, i: number) => string|number; loading?: boolean
  dynamicHeight?: boolean; estimatedHeight?: number
}>(), { headerHeight: 40, buffer: 10, loading: false, dynamicHeight: false, estimatedHeight: 48 })

const DYNAMIC_HEIGHT_WARNING = 'VirtualTable: dynamicHeight is declared but measurement is not implemented. Use VirtualList for dynamic heights.'

const emit = defineEmits<{
  rowClick: [item: T, index: number]
  sort: [key: string, order: 'asc'|'desc']
  visibleChange: [startIndex: number, endIndex: number]
}>()

const containerRef = ref<HTMLElement|null>(null)
const scrollTop = ref(0), sortKey = ref(''), sortOrder = ref<'asc'|'desc'>('desc')
const buf = computed(() => props.buffer ?? 10)
const bodyH = computed(() => props.containerHeight - props.headerHeight)
const estimatedH = computed(() => props.dynamicHeight ? props.estimatedHeight : props.itemHeight)

// Non-reactive height cache — avoids triggering full prefix-sum recomputation on every measurement
const _heightMap = new Map<number, number>()
const _itemCountRef = ref(0)

function _getItemHeight(index: number): number {
  if (!props.dynamicHeight) return props.itemHeight
  return _heightMap.get(index) || estimatedH.value
}

const _prefixSums = computed(() => {
  if (!props.dynamicHeight) return null
  // Only recompute when item count changes, not on every height measurement
  void _itemCountRef.value
  // If no heights have been measured, return null to use simple multiplication
  if (_heightMap.size === 0) return null
  const n = props.items.length
  const sums = new Float64Array(n + 1)
  for (let i = 0; i < n; i++) {
    sums[i + 1] = sums[i] + (_heightMap.get(i) || estimatedH.value)
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
  if (heightCache.value.length === 0) return Math.floor(scrollPos / estimatedH.value)
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
  if (_prefixSums.value) return _prefixSums.value[props.items.length]
  return props.items.length * estimatedH.value
})

const startIdx = computed(() => Math.max(0, findStartIndex(scrollTop.value) - buf.value))
const visCount = computed(() => { if (estimatedH.value <= 0 || bodyH.value <= 0) return buf.value * 2; return Math.ceil(bodyH.value / estimatedH.value) + buf.value * 2 })
const endIdx = computed(() => Math.min(props.items.length, startIdx.value + visCount.value))
const visibleItems = computed(() => { const r: {raw:T,index:number}[] = []; for (let i=startIdx.value;i<endIdx.value;i++) if(i<props.items.length) r.push({raw:props.items[i],index:i}); return r })
const offsetY = computed(() => {
  if (!props.dynamicHeight) return startIdx.value * props.itemHeight
  return getPosition(startIdx.value)
})

function getItemStyle(index: number) {
  if (!props.dynamicHeight) return { height: `${props.itemHeight}px` }
  return { height: `${_heightMap.get(index) || estimatedH.value}px` }
}

function itemKey(item: {raw:T,index:number}) { return props.itemKeyFn ? props.itemKeyFn(item.raw,item.index) : item.index }

let rafId: number|null = null
function onScroll() {
  if(rafId!==null) return
  rafId = requestAnimationFrame(()=>{
    if(containerRef.value) {
      const body = containerRef.value.querySelector('.vt-body') as HTMLElement
      if(body) scrollTop.value = body.scrollTop
    }
    rafId=null
  })
}

function handleSort(col: ColDef) { if(sortKey.value===col.key) sortOrder.value = sortOrder.value==='asc'?'desc':'asc'; else { sortKey.value=col.key; sortOrder.value='desc' } emit('sort', col.key, sortOrder.value) }
function scrollToIndex(i: number) { const b = containerRef.value?.querySelector('.vt-body') as HTMLElement; if(!b) return; if(props.dynamicHeight) b.scrollTop = getPosition(i); else b.scrollTop = i * props.itemHeight }

watch(()=>props.items.length,(n,o)=>{ if(n!==o){ _itemCountRef.value=n; if(scrollTop.value>totalHeight.value) nextTick(()=>scrollToIndex(0)) } })
watch([startIdx, endIdx], ([s, e]) => { emit('visibleChange', s, e) })

let ro: ResizeObserver|null = null
onMounted(()=>{ if(props.dynamicHeight) console.warn(DYNAMIC_HEIGHT_WARNING); const b = containerRef.value?.querySelector('.vt-body') as HTMLElement; if(b&&typeof ResizeObserver!=='undefined'){ro=new ResizeObserver(onScroll);ro.observe(b)} })
onUnmounted(()=>{ ro?.disconnect(); if(rafId!==null) cancelAnimationFrame(rafId) })
defineExpose({ scrollToIndex, scrollToTop:()=>scrollToIndex(0), scrollToBottom:()=>scrollToIndex(props.items.length-1) })
</script>

<style scoped>
.vt-container{position:relative;overflow:hidden;border:1px solid #e5e7eb;border-radius:6px}
.vt-header{display:flex;background:#f9fafb;border-bottom:2px solid #e5e7eb;position:sticky;top:0;z-index:10}
.vt-th{display:flex;align-items:center;padding:0 12px;font-weight:600;font-size:13px;color:#374151;user-select:none;border-right:1px solid #e5e7eb}
.vt-th:last-child{border-right:none}
.sort-ind{margin-left:4px;font-size:12px;color:#3b82f6}
.vt-body{position:relative;overflow-y:auto;overflow-x:hidden;will-change:scroll-position}
.vt-phantom{position:absolute;top:0;left:0;right:0;z-index:-1}
.vt-content{position:absolute;top:0;left:0;right:0;will-change:transform}
.vt-row{display:flex;box-sizing:border-box;border-bottom:1px solid #e5e7eb;cursor:pointer;transition:background-color .1s}
.vt-row:hover{background-color:#f3f4f6}
.vt-td{display:flex;align-items:center;padding:0 12px;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border-right:1px solid #e5e7eb}
.vt-td:last-child{border-right:none}
.vt-loading{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);padding:12px 24px;background:rgba(255,255,255,.9);border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1);z-index:20}
</style>

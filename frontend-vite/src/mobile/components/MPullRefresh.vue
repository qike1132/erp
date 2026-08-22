<template>
  <div ref="containerRef" class="m-pull-refresh" @touchstart="onTouchStart" @touchmove="onTouchMove" @touchend="onTouchEnd">
    <!-- 下拉指示器 -->
    <div class="m-pr-indicator" :style="{ height: pullDistance + 'px', opacity: pullDistance / threshold }">
      <div class="m-pr-spinner" :class="{ loading: isRefreshing }">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="20" height="20">
          <path d="M21 12a9 9 0 1 1-6.219-8.56" stroke-linecap="round" />
        </svg>
      </div>
      <span class="m-pr-text">{{ isRefreshing ? '刷新中…' : pullDistance >= threshold ? '释放刷新' : '下拉刷新' }}</span>
    </div>

    <!-- 内容区域 -->
    <div class="m-pr-content" :style="{ transform: `translateY(${pullDistance}px)` }">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'

const emit = defineEmits<{ (e: 'refresh', done: () => void): void }>()

const containerRef = ref<HTMLElement>()
const pullDistance = ref(0)
const isRefreshing = ref(false)
const startY = ref(0)
const threshold = 64

let pulling = false

function onTouchStart(e: TouchEvent) {
  if (isRefreshing.value) return
  const scrollTop = containerRef.value?.scrollTop ?? 0
  if (scrollTop > 0) return
  const touch = e.touches[0]
  if (!touch) return
  startY.value = touch.clientY
  pulling = true
}

function onTouchMove(e: TouchEvent) {
  if (!pulling || isRefreshing.value) return
  const touch = e.touches[0]
  if (!touch) return
  const dy = touch.clientY - startY.value
  if (dy < 0) {
    pullDistance.value = 0
    return
  }
  pullDistance.value = Math.min(dy * 0.5, threshold * 1.5)
}

function onTouchEnd() {
  if (!pulling) return
  pulling = false

  if (pullDistance.value >= threshold && !isRefreshing.value) {
    isRefreshing.value = true
    pullDistance.value = threshold

    emit('refresh', () => {
      isRefreshing.value = false
      pullDistance.value = 0
    })
  } else {
    pullDistance.value = 0
  }
}

onUnmounted(() => {
  pulling = false
  isRefreshing.value = false
})
</script>

<style scoped>
.m-pull-refresh {
  position: relative;
  min-height: 100%;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.m-pr-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  overflow: hidden;
  transition: height 0.2s var(--m-ease-smooth);
  color: var(--m-text-secondary);
}

.m-pr-spinner {
  transition: transform 0.3s var(--m-ease-smooth);
}

.m-pr-spinner.loading {
  animation: m-spin 0.8s linear infinite;
}

@keyframes m-spin {
  to { transform: rotate(360deg); }
}

.m-pr-text {
  font-size: var(--m-font-label-sm);
  font-weight: var(--m-font-weight-medium);
}

.m-pr-content {
  transition: transform 0.3s var(--m-ease-spring);
}
</style>

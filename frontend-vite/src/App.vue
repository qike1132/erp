<template>
  <a href="#main-content" class="skip-link" aria-label="跳到主内容">跳到主内容</a>
  <router-view />
  <!-- 路由 chunk 加载指示：顶部细进度条，不再全屏遮罩阻塞交互 -->
  <Transition name="route-loading-fade">
    <div
      v-if="showRouteLoading"
      class="route-loading-bar"
      role="status"
      aria-live="polite"
      aria-label="页面加载中"
    />
  </Transition>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useRouter, type RouteLocationNormalized } from 'vue-router'

// 全局路由导航 loading：仅覆盖懒加载组件 chunk 首次下载期的空白
// - 已缓存的 chunk（二次导航）不显示 loading，避免闪烁
// - 延迟 800ms 后再显示，只对真正缓慢的 chunk 下载提示（本地开发/缓存命中几乎不出现）
const router = useRouter()
const showRouteLoading = ref(false)
let loadingTimer: ReturnType<typeof setTimeout> | null = null

const DELAY_MS = 800

/** 检查目标路由是否包含未解析的动态 import（即 chunk 尚未缓存） */
function hasUnresolvedChunk(to: RouteLocationNormalized): boolean {
  return to.matched.some((r) => {
    const comp = r.components?.default
    return typeof comp === 'function'
  })
}

function startRouteLoading(to: RouteLocationNormalized) {
  // 所有组件 chunk 已缓存 → 无需 loading，导航几乎瞬时完成
  if (!hasUnresolvedChunk(to)) return
  if (loadingTimer) return
  loadingTimer = setTimeout(() => {
    showRouteLoading.value = true
  }, DELAY_MS)
}

function stopRouteLoading() {
  if (loadingTimer) {
    clearTimeout(loadingTimer)
    loadingTimer = null
  }
  showRouteLoading.value = false
}

const removeBefore = router.beforeEach(startRouteLoading)
const removeAfter = router.afterEach(stopRouteLoading)
// 导航失败（如 chunk 加载失败、守卫抛错）时 afterEach 不会触发，
// 必须同时在 onError 里关闭 loading，否则遮罩层会永久转圈
const removeError = router.onError(() => stopRouteLoading())

onUnmounted(() => {
  removeBefore()
  removeAfter()
  removeError()
})
</script>

<style scoped>
.skip-link {
  position: absolute;
  top: -100%;
  left: 0;
  z-index: 99999;
  padding: 8px 16px;
  background: var(--color-ocean);
  color: white;
  font-weight: 700;
  font-size: 14px;
  border-radius: 0 0 8px 0;
  text-decoration: none;
  transition: top 0.2s ease;
}
.skip-link:focus-visible {
  top: 0;
}

.route-loading-bar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  z-index: 9999;
  overflow: hidden;
  pointer-events: none;
}

.route-loading-bar::after {
  content: '';
  display: block;
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, var(--color-ocean-deep, #1e6b8c), var(--color-ocean, #2a8bb8));
  border-radius: 0 2px 2px 0;
  animation: route-loading-slide 1s ease-in-out infinite;
}

@keyframes route-loading-slide {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(350%);
  }
}

.route-loading-fade-enter-active,
.route-loading-fade-leave-active {
  transition: opacity 0.2s ease;
}

.route-loading-fade-enter-from,
.route-loading-fade-leave-to {
  opacity: 0;
}
</style>

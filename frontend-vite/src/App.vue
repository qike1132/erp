<template>
  <a href="#main-content" class="skip-link">跳到主内容</a>
  <router-view />
  <Transition name="route-loading-fade">
    <div
      v-if="showRouteLoading"
      class="route-loading-overlay"
      role="status"
      aria-live="polite"
      aria-label="页面加载中"
    >
      <div class="route-loading-box">
        <div class="route-loading-spinner" />
        <span class="route-loading-text">正在进入系统…</span>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

// 全局路由导航 loading：覆盖懒加载组件 chunk 下载期的空白
// （如登录成功后跳转 /dashboard，DefaultLayout/DashboardView 首次加载时）
const router = useRouter()
const showRouteLoading = ref(false)
let loadingTimer: ReturnType<typeof setTimeout> | null = null

// 150ms 延迟：已缓存的路由切换（瞬时完成）不闪烁 loading
const DELAY_MS = 150

function startRouteLoading() {
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
const removeError = router.onError(stopRouteLoading)

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

.route-loading-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-surface, #f7f9fc);
}

.route-loading-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

.route-loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--color-border, #e2e8f0);
  border-top-color: var(--color-ocean-deep, #1e6b8c);
  border-radius: 50%;
  animation: route-loading-spin 0.7s linear infinite;
}

.route-loading-text {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-secondary, #64748b);
}

@keyframes route-loading-spin {
  to {
    transform: rotate(360deg);
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

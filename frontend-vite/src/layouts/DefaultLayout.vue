<template>
  <div class="app-layout">
    <div v-if="isMobileOverlay" class="sidebar-overlay" @click="isCollapsed = true" />
    <AppSidebar :collapsed="isCollapsed" />
    <div class="main-content" :class="{ 'no-header': hideChrome }">
      <header v-if="!hideChrome" class="top-header">
        <div class="header-left">
          <button class="menu-toggle-btn" @click="isCollapsed = !isCollapsed">
            <i :class="!isCollapsed ? 'fas fa-angles-left' : 'fas fa-angles-right'" style="font-size: 18px" />
          </button>
          <button class="home-btn" @click="router.push('/dashboard')">
            <i class="fas fa-home" style="font-size: 14px" />
            返回首页
          </button>
        </div>
        <div class="header-right">
          <span class="header-clock">
            <i class="fas fa-clock" style="font-size: 13px" />
            {{ currentTime }}
          </span>
          <div class="user-info-header">
            <div class="user-avatar-header">
              {{ avatarLetter }}
            </div>
            <div class="user-info-details">
              <div class="user-name-header">
                {{ authStore.user?.username || '用户' }}
              </div>
              <div class="user-role-header">
                {{ authStore.user?.isSuper ? '超级管理员' : '普通用户' }}
              </div>
            </div>
          </div>
          <button class="logout-btn-header" @click="handleLogout">
            <i class="fas fa-right-from-bracket" style="font-size: 13px" />
            <span>退出</span>
          </button>
        </div>
      </header>
      <TabBar />
      <div class="content-container" :class="{ 'no-padding': hideChrome }">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useTabStore } from '@/stores/tabs'
import AppSidebar from './components/AppSidebar.vue'
import TabBar from './components/TabBar.vue'

const MOBILE_BREAKPOINT = 768

const authStore = useAuthStore()
const tabStore = useTabStore()
const router = useRouter()
const route = useRoute()
const isCollapsed = ref(false)
const hideChrome = computed(() => route.path !== '/dashboard')
const currentTime = ref('')
const windowWidth = ref(window.innerWidth)
const avatarLetter = computed(() => (authStore.user?.username || 'U').charAt(0).toUpperCase())

const isMobileOverlay = computed(() => windowWidth.value < MOBILE_BREAKPOINT && !isCollapsed.value)

function handleResize() {
  windowWidth.value = window.innerWidth
  if (windowWidth.value < MOBILE_BREAKPOINT) {
    isCollapsed.value = true
  }
}

// 移动端路由切换时自动收起侧边栏 + 更新标签栏
watch(
  () => route.path,
  (path) => {
    if (windowWidth.value < MOBILE_BREAKPOINT) {
      isCollapsed.value = true
    }
    tabStore.addOrActivate(path)
  },
  { immediate: true },
)

let timer: ReturnType<typeof setInterval> | null = null

function updateTime() {
  const now = new Date()
  currentTime.value = now.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(() => {
  updateTime()
  timer = setInterval(updateTime, 60_000)
  window.addEventListener('resize', handleResize)
  handleResize()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', handleResize)
})

async function handleLogout() {
  try {
    await authApi.logout()
  } finally {
    authStore.logout()
    tabStore.clear()
    router.push('/login')
  }
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  position: relative;
  background: var(--color-surface);
  box-sizing: border-box;
}

.sidebar-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 200;
  transition: opacity 0.3s ease;
}

.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, var(--color-surface) 0%, var(--color-border-light) 100%);
  border-radius: 14px;
  overflow: hidden;
  margin: 4px 4px 4px 0;
}

.top-header {
  background: rgba(255, 255, 255, 0.95);
  padding: 16px 32px;
  border-bottom: 3px solid var(--color-ocean-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow:
    0 4px 20px color-mix(in srgb, var(--color-ocean) 25%, transparent),
    0 2px 8px rgba(0, 0, 0, 0.05);
  position: sticky;
  top: 0;
  z-index: 100;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.menu-toggle-btn {
  background: var(--color-surface-card);
  border: 2px solid var(--color-ocean);
  color: var(--color-text);
  width: 44px;
  height: 44px;
  border-radius: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: transform 0.2s ease, background 0.2s ease;
  box-shadow: 0 2px 8px rgba(176, 224, 230, 0.25);
  will-change: transform;
}

.menu-toggle-btn:hover {
  background: var(--color-ocean-light);
  transform: scale(1.05);
}

.home-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--color-surface-card);
  border: 2px solid var(--color-ocean);
  border-radius: 14px;
  padding: 12px 24px;
  cursor: pointer;
  color: var(--color-text);
  font-size: 14px;
  font-weight: 600;
  position: relative;
  overflow: hidden;
  min-height: 44px;
  box-shadow:
    0 4px 12px color-mix(in srgb, var(--color-ocean) 25%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  transition:
    color 0.4s cubic-bezier(0.4, 0, 0.2, 1),
    transform 0.4s cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1),
    border-color 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.home-btn::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.6), transparent);
  transition: left 0.5s;
}

.home-btn:hover {
  background: var(--color-surface-card);
  color: var(--color-text);
  transform: translateY(-3px) scale(1.02);
  box-shadow:
    0 8px 25px color-mix(in srgb, var(--color-ocean-deep) 35%, transparent),
    0 4px 12px rgba(0, 0, 0, 0.1),
    inset 0 1px 0 rgba(255, 255, 255, 0.3);
  border-color: var(--color-ocean-deep);
}

.home-btn:hover::before {
  left: 100%;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 20px;
}

.header-clock {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-tertiary);
  font-size: 13px;
  font-weight: 500;
}

.user-info-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 18px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9) 0%, rgba(240, 244, 248, 0.9) 100%);
  box-shadow:
    0 2px 12px color-mix(in srgb, var(--color-ocean) 25%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  border: 2px solid var(--color-ocean-light);
  transition:
    transform 0.35s ease,
    box-shadow 0.35s ease,
    border-color 0.35s ease;
}

.user-info-header:hover {
  transform: translateY(-2px);
  box-shadow:
    0 6px 20px color-mix(in srgb, var(--color-ocean-deep) 35%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 1);
  border-color: var(--color-ocean-deep);
}

.user-avatar-header {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--color-ocean) 0%, var(--color-ocean-deep) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-inverse);
  font-weight: 700;
  font-size: 15px;
  box-shadow: 0 3px 10px color-mix(in srgb, var(--color-ocean) 25%, transparent);
  flex-shrink: 0;
}

.user-info-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-name-header {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1.2;
}

.user-role-header {
  font-size: 11px;
  color: var(--color-text-tertiary);
  opacity: 0.85;
  line-height: 1.2;
}

.logout-btn-header {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  border-radius: 14px;
  border: 2px solid var(--color-danger-200);
  background: linear-gradient(135deg, var(--color-danger-50) 0%, var(--color-danger-100) 100%);
  color: var(--color-danger-800);
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
  transition:
    transform 0.35s cubic-bezier(0.4, 0, 0.2, 1),
    background 0.35s cubic-bezier(0.4, 0, 0.2, 1),
    box-shadow 0.35s cubic-bezier(0.4, 0, 0.2, 1),
    border-color 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow:
    0 3px 10px color-mix(in srgb, var(--color-danger-200) 30%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  white-space: nowrap;
}

.logout-btn-header:hover {
  background: linear-gradient(135deg, var(--color-danger-100) 0%, var(--color-danger-200) 100%);
  transform: translateY(-2px);
  box-shadow:
    0 6px 18px color-mix(in srgb, var(--color-danger-200) 45%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
  border-color: var(--color-danger-300);
}

.content-container {
  flex: 1;
  min-height: 0;
  padding: 24px;
  overflow-y: auto;
}

.content-container.no-padding {
  padding: 0;
  overflow-y: hidden;
}
</style>

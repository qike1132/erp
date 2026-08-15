<template>
  <div class="app-layout">
    <button v-if="isMobileOverlay" class="sidebar-overlay" aria-label="关闭侧边栏" @click="sidebarStore.setCollapsed(true)" />
    <AppSidebar :collapsed="sidebarStore.isCollapsed" />
    <div class="main-content" :class="{ 'no-header': hideChrome, 'immersive': hideChrome }">
      <div id="main-content" class="content-container" :class="{ 'no-padding': hideChrome }">
        <router-view />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useSidebarStore } from '@/stores/sidebar'
import AppSidebar from './components/AppSidebar.vue'

const MOBILE_BREAKPOINT = 768

const sidebarStore = useSidebarStore()
const route = useRoute()
const hideChrome = computed(() => !!route.meta.hideHeader)
const windowWidth = ref(window.innerWidth)

const isMobileOverlay = computed(() => windowWidth.value < MOBILE_BREAKPOINT && !sidebarStore.isCollapsed)

function handleResize() {
  windowWidth.value = window.innerWidth
  if (windowWidth.value < MOBILE_BREAKPOINT) {
    sidebarStore.setCollapsed(true)
  }
}

// 移动端路由切换时自动收起侧边栏
watch(
  () => route.path,
  () => {
    if (windowWidth.value < MOBILE_BREAKPOINT) {
      sidebarStore.setCollapsed(true)
    }
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('resize', handleResize)
  handleResize()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
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
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, var(--color-surface) 0%, var(--color-border-light) 100%);
  border-radius: 14px;
  overflow: hidden;
  margin: 4px 4px 4px 0;
}
.main-content.immersive {
  overflow: visible;
}

.content-container {
  flex: 1;
  min-height: 0;
  padding: 24px;
  overflow-y: auto;
  box-sizing: border-box;
}

.content-container.no-padding {
  padding: 0;
  overflow: visible;
}
</style>

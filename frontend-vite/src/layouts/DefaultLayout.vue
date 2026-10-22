<template>
  <div class="app-layout">
    <!--
      跳转主内容（WCAG 2.4.1）：必须是页面第一个可聚焦元素，
      否则键盘用户每次进页面都要 Tab 穿过整个侧边栏导航（审查 A11Y-17）。
      目标 #main-content 带 tabindex="-1"，否则浏览器只滚动不移动焦点，跳过形同虚设。
    -->
    <a class="skip-link" href="#main-content">跳到主内容</a>
    <button v-if="isMobileOverlay" class="sidebar-overlay" aria-label="关闭侧边栏" @click="sidebarStore.setCollapsed(true)" />
    <AppSidebar :collapsed="sidebarStore.isCollapsed" />
    <div class="main-content" :class="{ 'no-header': hideChrome, 'immersive': hideChrome }">
      <div id="main-content" tabindex="-1" class="content-container" :class="{ 'no-padding': hideChrome }">
        <!-- keep-alive 仅缓存 PatternRoomView：离开再进入不销毁组件，数据与滚动位置保留，
             二次进入零请求零加载；其它路由（含带计时器的 Dashboard）不缓存，避免残留后台任务 -->
        <router-view v-slot="{ Component }">
          <keep-alive :include="['PatternRoomView']">
            <component :is="Component" />
          </keep-alive>
        </router-view>
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
/* 跳转主内容链接：默认移出视口，获得焦点后滑入。
   用 transform 而非 display:none —— 后者会让它无法被聚焦，跳过链接就失效了。 */
.skip-link {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 300;
  padding: 8px 14px;
  border-radius: 8px;
  background: var(--color-primary-700, #2d5ab8);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  transform: translateY(-200%);
  transition: transform 0.15s ease;
}

.skip-link:focus {
  transform: translateY(0);
}

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

<template>
  <header class="m-navbar" :class="{ transparent, 'has-subtitle': !!subtitle }">
    <button v-if="showBack" class="m-navbar-back" aria-label="返回" @click="handleBack">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
        <polyline points="15 18 9 12 15 6" />
      </svg>
    </button>
    <div class="m-navbar-center">
      <h1 class="m-navbar-title">{{ title }}</h1>
      <p v-if="subtitle" class="m-navbar-subtitle">{{ subtitle }}</p>
    </div>
    <div class="m-navbar-right">
      <slot name="right" />
    </div>
  </header>
</template>

<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'

defineProps<{
  title: string
  subtitle?: string
  showBack?: boolean
  transparent?: boolean
}>()

const router = useRouter()
const route = useRoute()

function handleBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/')
  }
}
</script>

<style scoped>
.m-navbar {
  display: flex;
  align-items: center;
  padding: var(--m-safe-top) 16px 8px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 0.5px solid rgba(0, 0, 0, 0.06);
  min-height: 44px;
  flex-shrink: 0;
  position: sticky;
  top: 0;
  z-index: 50;
}

.m-navbar.transparent {
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border-bottom: none;
}

.m-navbar-back {
  width: var(--m-touch-min);
  height: var(--m-touch-min);
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: none;
  color: var(--m-accent);
  cursor: pointer;
  margin-left: -8px;
  flex-shrink: 0;
  -webkit-tap-highlight-color: transparent;
}

.m-navbar-back:active {
  opacity: 0.5;
}

.m-navbar-center {
  flex: 1;
  min-width: 0;
  text-align: center;
}

.m-navbar-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--m-text-primary);
  line-height: 1.2;
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.m-navbar-subtitle {
  font-size: 12px;
  color: var(--m-text-secondary);
  margin: 2px 0 0;
  line-height: 1.2;
}

.m-navbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-right: -8px;
  flex-shrink: 0;
}
</style>

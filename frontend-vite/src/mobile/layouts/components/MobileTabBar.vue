<template>
  <nav class="m-tabbar" role="tablist">
    <button
      v-for="tab in tabs"
      :key="tab.name"
      :class="['m-tabbar-item', { active: activeTab === tab.name, center: tab.center }]"
      :aria-label="tab.label"
      :aria-selected="activeTab === tab.name"
      role="tab"
      @click="handleTab(tab)"
    >
      <template v-if="tab.center">
        <div class="m-tabbar-center">
          <component :is="tab.icon" />
        </div>
      </template>
      <template v-else>
        <component :is="tab.icon" class="m-tabbar-icon" />
        <span class="m-tabbar-label">{{ tab.label }}</span>
      </template>
    </button>
  </nav>
</template>

<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'

interface TabItem {
  name: string
  label: string
  icon: Component
  to?: string
  center?: boolean
}

const props = defineProps<{ tabs: TabItem[] }>()
const emit = defineEmits<{ (e: 'tab-click', name: string): void }>()

const route = useRoute()
const router = useRouter()

const activeTab = computed(() => {
  for (const tab of props.tabs) {
    if (tab.to && route.path.startsWith(tab.to)) return tab.name
  }
  // F5-2：无匹配 tab（快捷面板六页等）不得兜底高亮第一个 tab，否则「概览」误亮
  return ''
})

function handleTab(tab: TabItem) {
  if (tab.center) {
    emit('tab-click', tab.name)
    return
  }
  if (tab.to) {
    router.push(tab.to)
  }
}
</script>

<style scoped>
.m-tabbar {
  flex-shrink: 0;
  display: flex;
  justify-content: space-around;
  align-items: center;
  padding: 6px 12px calc(6px + var(--m-safe-bottom));
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border-top: 0.5px solid rgba(0, 0, 0, 0.04);
}

.m-tabbar-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 6px 12px;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--m-text-tertiary);
  transition: color 0.3s var(--m-ease-smooth), transform 0.3s var(--m-ease-spring);
  font-family: inherit;
  position: relative;
  -webkit-tap-highlight-color: transparent;
}

.m-tabbar-item:active {
  transform: scale(0.88);
}

.m-tabbar-item.active {
  color: var(--m-accent);
}

.m-tabbar-item.active::after {
  content: '';
  position: absolute;
  top: -6px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 3px;
  border-radius: 2px;
  background: var(--m-accent);
}

.m-tabbar-icon {
  width: 22px;
  height: 22px;
  transition: color 0.3s var(--m-ease-smooth);
}

.m-tabbar-item.active .m-tabbar-icon {
  color: var(--m-accent);
}

.m-tabbar-label {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.2px;
  line-height: 1;
}

.m-tabbar-center {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  background: var(--m-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 14px rgba(0, 113, 227, 0.15);
  transition: transform 0.3s var(--m-ease-spring), box-shadow 0.3s var(--m-ease-smooth);
  margin-top: -14px;
  color: white;
}

.m-tabbar-center:active {
  transform: scale(0.92);
}

.m-tabbar-center :deep(svg) {
  width: 20px;
  height: 20px;
}
</style>

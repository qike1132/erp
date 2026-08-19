<template>
  <div v-for="section in sections" :key="'c' + section.title" class="sb-section">
    <router-link
      v-for="item in section.items"
      :key="item.path"
      :to="item.path"
      :class="['sb-nav-item', 'sb-nav-item-icon-only', { active: isActive(item.path) }]"
      @pointerenter="prefetchRoute(item.path)"
    >
      <div class="sb-nav-icon" :class="{ 'sb-nav-icon-active': isActive(item.path) }">
        <i :class="resolveIcon(item.icon)" aria-hidden="true" />
      </div>
    </router-link>
  </div>
</template>

<script setup lang="ts">
import type { NavSection } from '../composables/useSidebarNav'

defineProps<{
  sections: NavSection[]
  isActive: (path: string) => boolean
  resolveIcon: (icon: string | undefined) => string
  prefetchRoute: (path: string) => void
}>()
</script>

<style scoped>
.sb-section {
  margin-bottom: 8px;
}

.sb-nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  margin-bottom: 4px;
  border-radius: 12px;
  text-decoration: none;
  color: var(--color-heading);
  font-weight: 800;
  font-size: 14px;
  position: relative;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}

.sb-nav-item:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
  transform: translateY(-1px);
  border-color: var(--color-primary-200);
}

.sb-nav-item:hover .sb-nav-icon {
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sb-nav-item.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
}

.sb-nav-icon {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: var(--color-text-secondary);
  background: var(--color-surface);
  flex-shrink: 0;
  transition: color 0.3s ease, background 0.3s ease;
}

.sb-nav-icon-active {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-600);
}
</style>
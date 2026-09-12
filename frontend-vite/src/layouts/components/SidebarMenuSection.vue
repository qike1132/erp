<template>
  <div class="sb-section">
    <button
      type="button"
      class="sb-section-header"
      :class="{ open: isOpen }"
      :aria-expanded="isOpen"
      @click="emit('toggle')"
    >
      <span class="sb-section-title">{{ section.title }}</span>
      <span class="sb-chevron" aria-hidden="true" />
    </button>
    <div v-show="isOpen" class="sb-section-body">
      <router-link
        v-for="item in section.items"
        :key="item.path"
        :to="item.path"
        :class="['sb-nav-item', { active: isActive(item.path) }]"
        @pointerenter="prefetchRoute(item.path)"
      >
        <div class="sb-nav-icon" :class="{ 'sb-nav-icon-active': isActive(item.path) }">
          <FontAwesomeIcon :icon="resolveIcon(item.icon)" aria-hidden="true" />
        </div>
        <span class="sb-nav-label">{{ item.title }}</span>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { NavSection } from '../composables/useSidebarNav'

defineProps<{
  section: NavSection
  isOpen: boolean
  isActive: (path: string) => boolean
  resolveIcon: (icon: string | undefined) => string
  prefetchRoute: (path: string) => void
}>()

const emit = defineEmits<{ 'toggle': [] }>()
</script>

<style scoped>
.sb-section {
  margin-bottom: 8px;
}

.sb-section-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  margin-bottom: 4px;
  border-radius: 12px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0;
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease, background 0.2s ease;
}

.sb-section-header.open {
  color: var(--color-primary-700);
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}

.sb-section-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-chevron {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  margin-right: 2px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(-45deg);
  transition: transform 0.25s ease;
}

.sb-section-header.open .sb-chevron {
  transform: rotate(45deg);
}

.sb-section-body {
  padding-left: 4px;
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

.sb-nav-item.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
}

.sb-nav-item.active .sb-nav-label {
  color: var(--color-primary-700);
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

.sb-nav-label {
  transition: color 0.3s ease;
}
</style>
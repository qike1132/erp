<template>
  <aside :class="['sb-sidebar', { collapsed }]" aria-label="链接">
    <SidebarHeader :collapsed="collapsed" />
    <nav class="sb-nav">
      <SidebarCollapsedMenu
        v-if="collapsed"
        :sections="filteredSections"
        :is-active="isActive"
        :resolve-icon="resolveIcon"
        :prefetch-route="prefetchRoute"
      />
      <template v-else>
        <SidebarSearch v-model="searchQuery" />
        <SidebarMenuSection
          v-for="section in filteredSections"
          :key="section.title"
          :section="section"
          :is-open="sectionIsOpen(section.title)"
          :is-active="isActive"
          :resolve-icon="resolveIcon"
          :prefetch-route="prefetchRoute"
          @toggle="toggleSection(section.title)"
        />
      </template>
    </nav>
  </aside>
</template>

<script setup lang="ts">
import SidebarHeader from './SidebarHeader.vue'
import SidebarSearch from './SidebarSearch.vue'
import SidebarMenuSection from './SidebarMenuSection.vue'
import SidebarCollapsedMenu from './SidebarCollapsedMenu.vue'
import { useSidebarNav } from '../composables/useSidebarNav'

defineProps<{ collapsed: boolean }>()

const {
  searchQuery,
  filteredSections,
  isActive,
  prefetchRoute,
  resolveIcon,
  toggleSection,
  sectionIsOpen,
} = useSidebarNav()
</script>

<style scoped>
.sb-sidebar {
  width: 230px;
  min-width: 68px;
  flex-shrink: 0;
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1), transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  height: calc(100vh - 8px);
  margin: 4px 12px;
}

.sb-sidebar:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
  transform: translateY(-2px);
}

.sb-sidebar.collapsed {
  width: 68px;
}

.sb-sidebar.collapsed :deep(.sb-header) {
  padding: 16px 12px;
}

.sb-sidebar.collapsed :deep(.sb-logo) {
  justify-content: center;
  gap: 0;
}

.sb-sidebar.collapsed :deep(.sb-logo img) {
  width: 40px;
  height: 40px;
}

.sb-sidebar.collapsed :deep(.sb-nav-item) {
  justify-content: center;
  padding: 10px;
  gap: 0;
}

.sb-sidebar.collapsed :deep(.sb-nav-icon) {
  width: 36px;
  height: 36px;
  border-radius: 10px;
}

.sb-sidebar.collapsed :deep(.sb-section) {
  margin-bottom: 8px;
}

.sb-nav {
  flex: 1;
  padding: 14px 12px;
  overflow-y: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.sb-nav::-webkit-scrollbar {
  display: none;
}

@media (max-width: 767px) {
  .sb-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    z-index: 300;
    height: 100vh;
    margin: 0;
    border-radius: 0;
  }

  .sb-sidebar.collapsed {
    width: 0;
    min-width: 0;
    overflow: hidden;
    border-radius: 0;
    box-shadow: none;
  }
}
</style>

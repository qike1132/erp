<template>
  <div class="prs-split-layout">
    <aside v-if="!isNarrow" class="prs-left-pane" aria-label="链接">
      <div class="prs-left-content">
        <slot name="group-list" />
      </div>
    </aside>
    <button v-if="isNarrow" class="prs-drawer-trigger" aria-label="打开分组列表" @click="drawerOpen = true">
      <i class="fas fa-bars" aria-hidden="true" />
    </button>
    <main class="prs-right-pane">
      <slot name="detail-panel" />
    </main>
  </div>
  <UiDrawer
    v-if="isNarrow"
    :visible="drawerOpen"
    position="left"
    title="打样项目列表"
    width="320px"
    @update:visible="drawerOpen = $event"
  >
    <slot name="group-list" />
  </UiDrawer>
</template>

<script setup lang="ts">
import UiDrawer from '@/components/ui/UiDrawer.vue'

defineProps<{
  isNarrow: boolean
}>()

const drawerOpen = defineModel<boolean>('drawerOpen', { default: false })
</script>

<style scoped>
.prs-split-layout {
  display: flex;
  gap: 12px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.prs-left-pane {
  position: relative;
  flex: 0 0 680px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
  transition: flex-basis 0.25s ease;
  display: flex;
  flex-direction: column;
}
.prs-left-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.prs-drawer-trigger {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 10px;
  background: #fff;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  transition: all 0.2s ease;
}
.prs-drawer-trigger:hover {
  border-color: #ff9f43;
  color: #ff9f43;
}
.prs-right-pane {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
@media (max-width: 1023px) {
  .prs-split-layout {
    flex-direction: column;
  }
  .prs-right-pane {
    flex: 1;
  }
}
</style>
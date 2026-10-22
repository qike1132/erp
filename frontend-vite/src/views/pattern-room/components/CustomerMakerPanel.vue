<template>
  <!-- 版师列表：互斥筛选，选中态由 aria-pressed 表达（审查 A11Y-07） -->
  <div class="cgl-customer-list" role="group" aria-label="按版师筛选">
    <button
      v-for="group in groups"
      :key="group.pattern_maker_id ?? '_unassigned'"
      v-bind="selectionItemAttrs(isMakerSelected(group.pattern_maker_id))"
      :class="['cgl-customer-item', { active: isMakerSelected(group.pattern_maker_id) }]"
      @click="selectMaker(group.pattern_maker_id)"
    >
      <span class="cgl-customer-name">{{ group.pattern_maker_name || '未分配版师' }}</span>
      <span class="cgl-customer-count" aria-hidden="true">{{ group.project_count }}</span>
      <span class="sr-only">{{ group.project_count }} 个项目</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import type { PatternMakerGroup } from '@/api/patternRoom'
import { selectionItemAttrs } from '@/composables/useSelectionA11y'

defineProps<{
  groups: PatternMakerGroup[]
  isMakerSelected: (id: number | null) => boolean
  selectMaker: (id: number | null) => void
}>()
</script>

<style scoped>
.cgl-customer-list {
  flex: 0 0 120px;
  border-right: 1px solid var(--color-border-light, #e5e7eb);
  overflow-y: auto;
  background: transparent;
  padding: 4px 0;
}
.cgl-customer-item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 10px 10px;
  border: none;
  border-left: 3px solid transparent;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-primary);
  text-align: left;
  transition: all 0.15s;
}
.cgl-customer-item:hover {
  background: transparent;
}
.cgl-customer-item.active {
  border-left-color: #ff9f43;
  background: #ff9f4310;
  color: #ff9f43;
  font-weight: 600;
}
.cgl-customer-name {
  flex: 1;
  white-space: nowrap;
}
.cgl-customer-count {
  font-size: 10px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 8px;
  background: #ff9f4320;
  color: #ff9f43;
  flex-shrink: 0;
}
.cgl-customer-item.active .cgl-customer-count {
  background: #ff9f4340;
}
</style>
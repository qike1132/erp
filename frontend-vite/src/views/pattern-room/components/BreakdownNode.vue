<template>
  <div
    class="pr-bd-node"
    :class="`pr-bd-node--${node.item.category}`"
    :style="{ left: x + 'px', top: y + 'px', width: node.width + 'px' }"
    @click="$emit('select', node.item)"
  >
    <div class="pr-bd-node-icon">
      <i :class="categoryIcon" />
    </div>
    <div class="pr-bd-node-content">
      <div class="pr-bd-node-name" :title="node.item.material_name">{{ node.item.material_name || '(未命名)' }}</div>
      <div class="pr-bd-node-meta">
        <span class="pr-bd-node-qty">{{ node.item.quantity }} {{ node.item.unit }}</span>
        <span v-if="node.item.current_version" class="pr-bd-node-version">{{ node.item.current_version }}</span>
      </div>
      <div v-if="node.item.current_supplier_name" class="pr-bd-node-supplier">
        <i class="fas fa-truck" /> {{ node.item.current_supplier_name }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { BomItem } from '@/api/patternRoom'

interface TreeNode {
  item: BomItem
  children: TreeNode[]
  x: number
  y: number
  width: number
  height: number
}

const props = defineProps<{
  node: TreeNode
  x: number
  y: number
}>()

defineEmits<{
  select: [item: BomItem]
}>()

const categoryIcon = computed(() => {
  const map: Record<string, string> = {
    fabric: 'fas fa-square',
    filling: 'fas fa-cube',
    accessory: 'fas fa-link',
    packaging: 'fas fa-tag',
  }
  return map[props.node.item.category] || 'fas fa-circle'
})
</script>

<style scoped>
.pr-bd-node {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: white;
  border: 2px solid var(--color-border);
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  cursor: pointer;
  transition: all 0.2s;
  z-index: 1;
}

.pr-bd-node:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.1);
}

.pr-bd-node--fabric {
  border-color: var(--color-purple-300);
  background: linear-gradient(135deg, white, var(--color-purple-50));
}

.pr-bd-node--filling {
  border-color: var(--color-warning-300);
  background: linear-gradient(135deg, white, var(--color-warning-50));
}

.pr-bd-node--accessory {
  border-color: var(--color-info-300);
  background: linear-gradient(135deg, white, var(--color-info-50));
}

.pr-bd-node--packaging {
  border-color: var(--color-success-300);
  background: linear-gradient(135deg, white, var(--color-success-50));
}

.pr-bd-node-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.pr-bd-node--fabric .pr-bd-node-icon {
  color: var(--color-purple-600);
}

.pr-bd-node--filling .pr-bd-node-icon {
  color: var(--color-warning-600);
}

.pr-bd-node--accessory .pr-bd-node-icon {
  color: var(--color-info-600);
}

.pr-bd-node--packaging .pr-bd-node-icon {
  color: var(--color-success-600);
}

.pr-bd-node-content {
  flex: 1;
  min-width: 0;
}

.pr-bd-node-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pr-bd-node-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}

.pr-bd-node-qty {
  font-size: 11px;
  color: var(--color-text-secondary);
}

.pr-bd-node-version {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  background: var(--color-purple-100);
  color: var(--color-purple-700);
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}

.pr-bd-node-supplier {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pr-bd-node-supplier i {
  margin-right: 4px;
  font-size: 9px;
}
</style>

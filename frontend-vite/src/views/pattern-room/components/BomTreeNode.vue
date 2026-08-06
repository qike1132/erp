<template>
  <div class="pr-tree-node">
    <!-- 当前节点 -->
    <div class="pr-node-row" :style="{ paddingLeft: depth * 24 + 'px' }">
      <div class="pr-node-toggle" @click="toggleExpand">
        <i v-if="hasChildren" :class="['fas', item._expanded ? 'fa-chevron-down' : 'fa-chevron-right']" />
        <i v-else class="fas fa-circle pr-node-dot" />
      </div>

      <div class="pr-node-icon" :class="`pr-node-icon--${item.category}`">
        <i :class="categoryIcon" />
      </div>

      <div class="pr-node-fields">
        <input
          v-model="item.material_name"
          class="pr-input pr-input-name"
          placeholder="物料名称"
        />
        <select v-model="item.category" class="pr-input pr-input-category">
          <option value="fabric">面料</option>
          <option value="filling">填充</option>
          <option value="accessory">辅料</option>
          <option value="packaging">包装</option>
        </select>
        <input
          v-model.number="item.quantity"
          type="number"
          step="0.001"
          min="0"
          class="pr-input pr-input-qty"
          placeholder="用量"
        />
        <input
          v-model="item.unit"
          class="pr-input pr-input-unit"
          placeholder="单位"
        />
        <input
          v-model="item.spec"
          class="pr-input pr-input-spec"
          placeholder="规格"
        />
        <input
          v-model="item.current_supplier_name"
          class="pr-input pr-input-supplier"
          placeholder="供应商"
        />
        <input
          v-model="item.current_version"
          class="pr-input pr-input-version"
          placeholder="版本"
        />
      </div>

      <div class="pr-node-actions">
        <button class="pr-node-btn" title="添加子节点" @click="$emit('add-child', item)">
          <i class="fas fa-plus" />
        </button>
        <button class="pr-node-btn" title="上移" @click="$emit('move', { item, direction: 'up' })">
          <i class="fas fa-arrow-up" />
        </button>
        <button class="pr-node-btn" title="下移" @click="$emit('move', { item, direction: 'down' })">
          <i class="fas fa-arrow-down" />
        </button>
        <button class="pr-node-btn pr-node-btn-danger" title="删除" @click="$emit('remove', item)">
          <i class="fas fa-trash" />
        </button>
      </div>
    </div>

    <!-- 子节点 -->
    <div v-if="hasChildren && item._expanded" class="pr-node-children">
      <BomTreeNode
        v-for="(child, idx) in item.children"
        :key="idx"
        :item="child"
        :depth="depth + 1"
        @add-child="(p) => $emit('add-child', p)"
        @remove="(i) => $emit('remove', i)"
        @move="(p) => $emit('move', p)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BomTreeNode.vue — BOM 树节点（递归自调用）
 *
 * 职责：
 * - 渲染单个物料节点（名称/类别/用量/单位/规格/供应商/版本）
 * - 递归渲染子节点
 * - 通过事件向父级传递：add-child / remove / move
 */
import { computed } from 'vue'
import type { BomItem } from '@/api/patternRoom'

const props = defineProps<{
  item: BomItem
  depth: number
}>()

defineEmits<{
  'add-child': [item: BomItem]
  remove: [item: BomItem]
  move: [payload: { item: BomItem; direction: 'up' | 'down' }]
}>()

const hasChildren = computed(() => (props.item.children?.length ?? 0) > 0)

const categoryIcon = computed(() => {
  const map: Record<string, string> = {
    fabric: 'fas fa-square',
    filling: 'fas fa-cube',
    accessory: 'fas fa-link',
    packaging: 'fas fa-tag',
  }
  return map[props.item.category] || 'fas fa-circle'
})

function toggleExpand() {
  if (hasChildren.value) {
    props.item._expanded = !props.item._expanded
  }
}
</script>

<style scoped>
.pr-tree-node {
  display: flex;
  flex-direction: column;
}

.pr-node-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: white;
  border: 1px solid var(--color-border-light);
  margin-bottom: 6px;
  transition: border-color 0.2s;
}

.pr-node-row:hover {
  border-color: var(--color-primary-300);
}

.pr-node-toggle {
  cursor: pointer;
  width: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  font-size: 11px;
  flex-shrink: 0;
}

.pr-node-dot {
  font-size: 5px;
  color: var(--color-border);
}

.pr-node-icon {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  flex-shrink: 0;
}

.pr-node-icon--fabric {
  background: var(--color-purple-50);
  color: var(--color-purple-600);
}

.pr-node-icon--filling {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}

.pr-node-icon--accessory {
  background: var(--color-info-50);
  color: var(--color-info-600);
}

.pr-node-icon--packaging {
  background: var(--color-success-50);
  color: var(--color-success-600);
}

.pr-node-fields {
  display: flex;
  gap: 6px;
  flex: 1;
  flex-wrap: wrap;
}

.pr-input {
  padding: 5px 9px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 12px;
  outline: none;
  transition: border-color 0.2s;
  background: white;
  color: var(--color-text);
  font-family: inherit;
}

.pr-input:focus {
  border-color: var(--color-primary-400);
}

.pr-input-name {
  width: 160px;
  font-weight: 600;
}

.pr-input-category {
  width: 90px;
}

.pr-input-qty {
  width: 80px;
}

.pr-input-unit {
  width: 60px;
}

.pr-input-spec {
  width: 120px;
}

.pr-input-supplier {
  width: 140px;
}

.pr-input-version {
  width: 70px;
  text-align: center;
  font-weight: 600;
  color: var(--color-purple-700);
  background: var(--color-purple-50);
  border-color: var(--color-purple-200);
}

.pr-node-actions {
  display: flex;
  gap: 3px;
  flex-shrink: 0;
}

.pr-node-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-muted);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 11px;
}

.pr-node-btn:hover {
  border-color: var(--color-primary-400);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.pr-node-btn-danger:hover {
  border-color: var(--color-danger-400);
  color: var(--color-danger-600);
  background: var(--color-danger-50);
}

.pr-node-children {
  display: flex;
  flex-direction: column;
  padding-left: 0;
  border-left: 1px dashed var(--color-border);
  margin-left: 22px;
  padding-left: 8px;
}
</style>

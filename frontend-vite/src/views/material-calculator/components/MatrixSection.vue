<template>
  <!--
    跨角色对比矩阵：≥2 个作用域时展示；仅 1 个作用域时隐藏并提示（A-11）。
    默认折叠为 44px 摘要条 —— 常驻会让三列工作区丢掉约 37% 竖向预算。
    根节点为片段（两个互斥分支），不引入包装元素，保持 .page-card 的直接 flex 子项不变。
  -->
  <div v-if="matrix.visible" class="mc-matrix-section">
    <button
      class="mc-matrix-bar"
      :aria-expanded="open"
      aria-label="展开或收起跨角色对比矩阵"
      @click="open = !open"
    >
      <FontAwesomeIcon icon="table-cells" aria-hidden="true" />
      <span class="mc-matrix-bar-title">跨角色对比矩阵</span>
      <span class="mc-matrix-bar-meta">
        {{ matrix.scopes.length }} 个作用域 · {{ matrix.rows.length }} 行物料
      </span>
      <span class="mc-matrix-bar-toggle">
        {{ open ? '收起' : '展开' }}
        <FontAwesomeIcon
          icon="chevron-down"
          :class="['mc-matrix-caret', open ? 'expanded' : '']"
          aria-hidden="true"
        />
      </span>
    </button>
    <div v-if="open" class="mc-matrix-body">
      <RoleMatrix :scopes="matrix.scopes" :rows="matrix.rows" />
    </div>
  </div>
  <div v-else-if="matrix.reason === 'single-scope'" class="mc-matrix-hint">
    <FontAwesomeIcon icon="circle-info" aria-hidden="true" />
    当前仅 1 个作用域（无角色区分），无需跨角色对比
  </div>
</template>

<script setup lang="ts">
// 矩阵分区：折叠摘要条 + 展开体（或单作用域提示）。
// 从 MaterialCalculatorView.vue 抽出，纯粹为控制单 SFC 行数（门禁 ≤400 行），行为不变。
import { ref } from 'vue'
import type { RoleMatrixResult } from '@/utils/roleMatrix'
import RoleMatrix from './RoleMatrix.vue'

defineProps<{
  /** 由 calcGroups 派生的矩阵结果（纯函数产物） */
  matrix: RoleMatrixResult
}>()

// 默认收起：常驻会挤占三列工作区约 37% 的高度
const open = ref(false)
</script>

<style scoped>
.mc-matrix-section {
  flex-shrink: 0;
  margin: 0 var(--sp-5) var(--sp-4);
  border: var(--bw) solid var(--color-border);
  border-radius: var(--r-md);
  background: var(--color-surface-card);
  overflow: hidden;
}

.mc-matrix-bar {
  width: 100%;
  height: 44px;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 0 var(--sp-3);
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
  color: var(--color-text);
  transition: background 0.15s ease;
}
.mc-matrix-bar:hover {
  background: var(--color-surface);
}
.mc-matrix-bar :deep(svg) {
  width: 14px;
  height: 14px;
  color: var(--color-text-muted);
}
.mc-matrix-bar-title {
  font-size: var(--fs-xs);
  font-weight: 600;
}
.mc-matrix-bar-meta {
  font-size: var(--fs-cap);
  color: var(--color-text-muted);
}
.mc-matrix-bar-toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-cap);
  color: var(--color-primary-700);
}
.mc-matrix-caret {
  transition: transform 0.2s ease;
}
.mc-matrix-caret.expanded {
  transform: rotate(180deg);
}

.mc-matrix-body {
  border-top: var(--bw) solid var(--color-border-light);
  max-height: 340px;
  overflow: auto;
}

.mc-matrix-hint {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0 var(--sp-5) var(--sp-4);
  padding: 0 var(--sp-3);
  height: 40px;
  font-size: var(--fs-xs);
  color: var(--color-text-muted);
  border: var(--bw) solid var(--color-border-light);
  border-radius: var(--r-md);
  flex-shrink: 0;
}
</style>

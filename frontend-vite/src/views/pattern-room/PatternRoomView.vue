<template>
  <div class="pr-container">
    <div class="page-card page-card-main">
      <!-- 顶部：HeaderTabs + Tab 按钮 -->
      <div class="page-card-header pr-top-bar">
        <div class="pr-top-left"><HeaderTabs /></div>
        <div class="pr-top-right">
          <div class="pr-tab-group" role="tablist">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              role="tab"
              :aria-selected="activeTab === tab.key"
              :class="['pr-tab-btn', { active: activeTab === tab.key }]"
              @click="switchTab(tab.key)"
            >
              <i :class="tab.icon" aria-hidden="true" />
              <span>{{ tab.label }}</span>
              <span v-if="tab.key === 'bom' && bomCount > 0" class="count-badge-subtle">{{ bomCount }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="page-card-body pr-body">
        <BomTab v-if="activeTab === 'bom'" @count-update="(n) => (bomCount = n)" @view-breakdown="viewBreakdown" @view-compare="viewCompare" />
        <BreakdownTab v-else-if="activeTab === 'breakdown'" :bom-id="selectedBomId" />
        <VersionCompareTab v-else-if="activeTab === 'compare'" :bom-id="selectedBomId" />
        <ChangeLogTab v-else-if="activeTab === 'change-log'" :bom-id="selectedBomId" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * PatternRoomView.vue — 板房模块主容器
 *
 * 职责：
 * - 提供 4 个 Tab：BOM 管理 / 拆分图 / 版本对比 / 变更记录
 * - 通过 activeTab 控制标签页切换
 * - selectedBomId 在拆分图、版本对比、变更记录三个 Tab 间共享
 */
import { ref } from 'vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import BomTab from './BomTab.vue'
import BreakdownTab from './BreakdownTab.vue'
import VersionCompareTab from './VersionCompareTab.vue'
import ChangeLogTab from './ChangeLogTab.vue'

type TabKey = 'bom' | 'breakdown' | 'compare' | 'change-log'

const tabs: Array<{ key: TabKey; label: string; icon: string }> = [
  { key: 'bom', label: 'BOM 管理', icon: 'fas fa-list-tree' },
  { key: 'breakdown', label: '拆分图', icon: 'fas fa-sitemap' },
  { key: 'compare', label: '版本对比', icon: 'fas fa-code-compare' },
  { key: 'change-log', label: '变更记录', icon: 'fas fa-clock-rotate-left' },
]

const activeTab = ref<TabKey>('bom')
const selectedBomId = ref<number | null>(null)
const bomCount = ref(0)

function switchTab(key: TabKey) {
  activeTab.value = key
}

function viewBreakdown(bomId: number) {
  selectedBomId.value = bomId
  activeTab.value = 'breakdown'
}

function viewCompare(bomId: number) {
  selectedBomId.value = bomId
  activeTab.value = 'compare'
}
</script>

<style scoped>
.pr-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 100%;
}

.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

.pr-top-bar {
  flex-wrap: wrap;
  gap: 12px;
}

.pr-top-left {
  flex: 1 1 auto;
  min-width: 0;
}

.pr-top-right {
  flex: 0 0 auto;
}

.pr-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
}

.pr-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.pr-tab-btn:hover {
  background: var(--color-surface);
  color: var(--color-primary-700);
}

.pr-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
}

.pr-tab-btn i {
  font-size: 13px;
}

.pr-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
</style>

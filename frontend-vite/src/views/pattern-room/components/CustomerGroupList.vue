<template>
  <div class="cgl-container">
    <!-- 搜索框 -->
    <div class="cgl-search">
      <i class="fas fa-search cgl-search-icon" aria-hidden="true" />
      <input
        class="cgl-search-input"
        type="text"
        placeholder="搜索客户或项目..."
        @input="onSearchInput"
      />
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="cgl-loading">
      <UiSpinner size="sm" />
      <span>加载中...</span>
    </div>

    <!-- 空状态 -->
    <EmptyState
      v-else-if="!hasData"
      icon="fas fa-boxes"
      title="暂无打样项目"
      description="点击右上角「新增打样项目」创建第一个项目"
    />

    <!-- 客户分组列表 -->
    <div v-else class="cgl-list">
      <div v-for="group in groups" :key="group.customer_id ?? '_unassigned'" class="cgl-group">
        <!-- 分组标题 -->
        <button class="cgl-group-header" @click="toggleGroup(group.customer_id)">
          <i
            :class="[
              'fas',
              'cgl-chevron',
              isGroupOpen(group.customer_id) ? 'fa-chevron-down' : 'fa-chevron-right',
            ]"
            aria-hidden="true"
          />
          <span class="cgl-group-name">{{ group.customer_name || '未分配客户' }}</span>
          <span class="cgl-group-count">{{ group.project_count }}</span>
        </button>

        <!-- 分组下的项目卡片 -->
        <div v-show="isGroupOpen(group.customer_id)" class="cgl-projects">
          <button
            v-for="proj in group.projects"
            :key="proj.id"
            :class="['cgl-project-card', { active: selectedProjectId === proj.id }]"
            @click="$emit('select-project', proj.id)"
          >
            <div class="cgl-card-left">
              <div v-if="proj.product_image_url" class="cgl-card-thumb">
                <img :src="proj.product_image_url" alt="" />
              </div>
              <div v-else class="cgl-card-thumb cgl-card-thumb-placeholder">
                <i class="fas fa-tshirt" aria-hidden="true" />
              </div>
            </div>
            <div class="cgl-card-right">
              <div class="cgl-card-title">{{ proj.product_name }}</div>
              <div class="cgl-card-meta">
                <span class="cgl-card-seq">{{ proj.sequence_no }}</span>
                <span class="cgl-card-version">{{ proj.current_version }}</span>
              </div>
              <div class="cgl-card-time">{{ formatTime(proj.updated_at) }}</div>
            </div>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import EmptyState from './EmptyState.vue'
import type { CustomerGroup } from '@/api/patternRoom'

defineProps<{
  groups: CustomerGroup[]
  loading: boolean
  hasData: boolean
  selectedProjectId: number | null
}>()

const emit = defineEmits<{
  'select-project': [id: number]
  search: [keyword: string]
  'add-project': []
}>()

/** 展开的分组 key 集合 */
const openGroups = ref<Set<string>>(new Set())

function groupKey(customerId: number | null): string {
  return customerId != null ? String(customerId) : '_unassigned'
}

function isGroupOpen(customerId: number | null): boolean {
  return openGroups.value.has(groupKey(customerId))
}

function toggleGroup(customerId: number | null) {
  const key = groupKey(customerId)
  if (openGroups.value.has(key)) {
    openGroups.value.delete(key)
  } else {
    openGroups.value.add(key)
  }
}

function onSearchInput(e: Event) {
  const target = e.target as HTMLInputElement
  emit('search', target.value)
}

function formatTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 默认展开第一个分组
import { watch } from 'vue'
watch(
  () => (defineProps as any).groups,
  (g: CustomerGroup[]) => {
    if (g && g.length > 0 && openGroups.value.size === 0) {
      openGroups.value.add(groupKey(g[0].customer_id))
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.cgl-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* 搜索 */
.cgl-search {
  position: relative;
  padding: 12px;
  border-bottom: 1px solid var(--color-border-light, #e5e7eb);
  flex-shrink: 0;
}

.cgl-search-icon {
  position: absolute;
  left: 22px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-secondary, #9ca3af);
  font-size: 12px;
}

.cgl-search-input {
  width: 100%;
  padding: 8px 12px 8px 30px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  font-size: 13px;
  background: var(--color-surface, #f9fafb);
  color: var(--color-text-primary);
  outline: none;
  box-sizing: border-box;
}

.cgl-search-input:focus {
  border-color: var(--color-primary-400);
}

/* 加载 */
.cgl-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 0;
  color: var(--color-text-secondary, #9ca3af);
  font-size: 13px;
}

/* 分组 */
.cgl-list {
  flex: 1;
  overflow-y: auto;
}

.cgl-group {
  border-bottom: 1px solid var(--color-border-light, #e5e7eb);
}

.cgl-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  background: var(--color-surface, #f9fafb);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  text-align: left;
  transition: background 0.15s;
}

.cgl-group-header:hover {
  background: var(--color-surface-hover, #f3f4f6);
}

.cgl-chevron {
  font-size: 10px;
  color: var(--color-text-secondary);
  width: 12px;
  transition: transform 0.2s;
}

.cgl-group-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cgl-group-count {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;
  background: #ff9f4320;
  color: #ff9f43;
}

/* 项目卡片 */
.cgl-projects {
  padding: 4px 8px 8px;
}

.cgl-project-card {
  display: flex;
  gap: 10px;
  width: 100%;
  padding: 8px;
  margin-bottom: 4px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
}

.cgl-project-card:hover {
  border-color: #ff9f4340;
  background: #ff9f4308;
}

.cgl-project-card.active {
  border-color: #ff9f43;
  background: #ff9f4310;
}

.cgl-card-left {
  flex-shrink: 0;
}

.cgl-card-thumb {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--color-surface, #f3f4f6);
  display: flex;
  align-items: center;
  justify-content: center;
}

.cgl-card-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cgl-card-thumb-placeholder i {
  font-size: 16px;
  color: var(--color-text-secondary);
  opacity: 0.5;
}

.cgl-card-right {
  flex: 1;
  min-width: 0;
}

.cgl-card-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cgl-card-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-bottom: 2px;
}

.cgl-card-seq {
  font-size: 11px;
  color: var(--color-text-secondary);
}

.cgl-card-version {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: #3b82f620;
  color: #3b82f6;
  font-weight: 600;
}

.cgl-card-time {
  font-size: 11px;
  color: var(--color-text-secondary);
  opacity: 0.7;
}
</style>

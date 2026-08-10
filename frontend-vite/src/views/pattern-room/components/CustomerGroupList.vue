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

    <!-- 客户 + 项目双栏布局 -->
    <div v-else class="cgl-body">
      <!-- 左侧：客户名称列表 -->
      <div class="cgl-customer-list">
        <button
          v-for="group in groups"
          :key="group.customer_id ?? '_unassigned'"
          :class="['cgl-customer-item', { active: isCustomerSelected(group.customer_id) }]"
          @click="selectCustomer(group.customer_id)"
        >
          <span class="cgl-customer-name">{{ group.customer_name || '未分配客户' }}</span>
          <span class="cgl-customer-count">{{ group.project_count }}</span>
        </button>
      </div>

      <!-- 右侧：项目卡片 -->
      <div class="cgl-project-area">
        <div v-if="!selectedGroup" class="cgl-project-empty">
          <span>请选择一个客户</span>
        </div>
        <div v-else-if="selectedGroup.projects.length === 0" class="cgl-project-empty">
          <span>该客户暂无项目</span>
        </div>
        <div v-else class="cgl-projects">
          <button
            v-for="proj in selectedGroup.projects"
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
import { ref, computed, watch } from 'vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import EmptyState from './EmptyState.vue'
import type { CustomerGroup } from '@/api/patternRoom'

const props = defineProps<{
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

/** 当前选中的客户 key */
const selectedCustomerKey = ref<string | null>(null)

function groupKey(customerId: number | null): string {
  return customerId != null ? String(customerId) : '_unassigned'
}

function isCustomerSelected(customerId: number | null): boolean {
  return selectedCustomerKey.value === groupKey(customerId)
}

function selectCustomer(customerId: number | null) {
  selectedCustomerKey.value = groupKey(customerId)
}

/** 当前选中的分组 */
const selectedGroup = computed(() => {
  if (!selectedCustomerKey.value) return null
  return props.groups.find((g) => groupKey(g.customer_id) === selectedCustomerKey.value) ?? null
})

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

// 默认选中第一个分组
watch(
  () => props.groups,
  (g) => {
    if (g && g.length > 0 && selectedCustomerKey.value === null) {
      selectedCustomerKey.value = groupKey(g[0]!.customer_id)
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

/* 双栏主体 */
.cgl-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

/* 左侧：客户名称列表 */
.cgl-customer-list {
  flex: 0 0 150px;
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

/* 右侧：项目区域 */
.cgl-project-area {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 8px;
}

.cgl-project-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-text-secondary, #9ca3af);
  font-size: 13px;
}

/* 项目卡片 */
.cgl-projects {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cgl-project-card {
  display: flex;
  gap: 10px;
  width: 100%;
  padding: 8px;
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
  width: 200px;
  height: 200px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--color-surface, #f3f4f6);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.cgl-card-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.cgl-card-thumb-placeholder i {
  font-size: 48px;
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

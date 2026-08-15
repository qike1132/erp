<template>
  <div class="cgl-container">
    <!-- 搜索框 -->
    <div class="cgl-search">
      <i class="fas fa-search cgl-search-icon" aria-hidden="true" />
      <input
        class="cgl-search-input"
        type="text"
        placeholder="搜索版师或项目..."
        @input="onSearchInput"
      />
    </div>

    <!-- 状态筛选胶囊 -->
    <div class="cgl-status-filter">
      <button
        v-for="opt in STATUS_OPTIONS"
        :key="opt.value"
        type="button"
        :class="['cgl-status-btn', { active: statusFilter === opt.value }]"
        @click="onStatusChange(opt.value)"
      >
        {{ opt.label }}
      </button>
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

    <!-- 版师 + 项目双栏布局 -->
    <div v-else class="cgl-body">
      <!-- 左侧：版师姓名列表 -->
      <div class="cgl-customer-list">
        <button
          v-for="group in groups"
          :key="group.pattern_maker_id ?? '_unassigned'"
          :class="['cgl-customer-item', { active: isMakerSelected(group.pattern_maker_id) }]"
          @click="selectMaker(group.pattern_maker_id)"
        >
          <span class="cgl-customer-name">{{ group.pattern_maker_name || '未分配版师' }}</span>
          <span class="cgl-customer-count">{{ group.project_count }}</span>
        </button>
      </div>

      <!-- 右侧：项目卡片（虚拟滚动，仅渲染视口附近的卡片） -->
      <div ref="projectAreaRef" class="cgl-project-area">
        <div v-if="!selectedGroup" class="cgl-project-empty">
          <span>请选择一个版师</span>
        </div>
        <div v-else-if="selectedGroup.projects.length === 0" class="cgl-project-empty">
          <span>该版师暂无项目</span>
        </div>
        <VirtualList
          v-else-if="projectAreaHeight > 0"
          ref="virtualListRef"
          :items="selectedGroup.projects"
          :item-height="PROJECT_CARD_SLOT_H"
          :container-height="projectAreaHeight"
          :item-key="(p: ProjectSummary) => p.id"
          class="cgl-virtual-list"
        >
          <template #default="{ item: proj }">
            <ProjectCardItem
              :proj="proj"
              :selected="selectedProjectId === proj.id"
              :maker-name="selectedGroup?.pattern_maker_name"
              :display-number="projectDisplayNumbers.get(proj.id)"
              :can-manage="canManage"
              :thumb-loaded="thumbLoaded"
              @click="$emit('select-project', proj.id)"
              @keyup.enter="$emit('select-project', proj.id)"
              @preview="openImagePreview"
              @thumb-load="onThumbLoad"
              @edit="$emit('edit-project', $event)"
              @complete="$emit('complete-project', $event)"
              @cancel="$emit('cancel-project', $event)"
            />
          </template>
        </VirtualList>
        <!-- 兜底：测量高度失败时不显示空白，恢复后自动渲染 -->
        <div v-else class="cgl-project-empty" aria-live="polite">
          <UiSpinner size="sm" />
          <span>加载中...</span>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <UiPagination
      v-if="groupPages > 1"
      :current-page="groupPage"
      :total-pages="groupPages"
      :total-items="groupTotal"
      @update:current-page="$emit('update-group-page', $event)"
    />

    <!-- 图片查看模态框（与 product 页面共享样式） -->
    <Teleport to="body">
      <div v-if="previewImage" class="pd-overlay" @click.self="previewImage = null">
        <div class="pd-modal pd-modal-img-dialog">
          <div class="pd-modal-header">
            <h5 class="pd-modal-title">产品图片</h5>
            <button class="pd-modal-close" @click="previewImage = null" aria-label="关闭"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
          </div>
          <div class="pd-modal-body">
            <img :src="resolveStaticUrl(previewImage)" class="pd-modal-img-view" />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
/**
 * CustomerGroupList — 版师分组列表（搜索 + 状态筛选 + 双栏 + 虚拟滚动）
 * 拆分后职责：
 *  - 卡片行渲染 → ProjectCardItem
 *  - 虚拟滚动容器高度测量 → useVirtualAreaMeasure
 *  - 分组选择与项目编号 → useProjectGrouping
 */
import { ref, watch, toRef, nextTick } from 'vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import EmptyState from './EmptyState.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import ProjectCardItem from './ProjectCardItem.vue'
import { resolveStaticUrl } from '@/api/request'
import type { PatternMakerGroup, ProjectSummary } from '@/api/patternRoom'
import { useVirtualAreaMeasure } from '../composables/useVirtualAreaMeasure'
import { useProjectGrouping } from '../composables/useProjectGrouping'

const props = defineProps<{
  groups: PatternMakerGroup[]
  loading: boolean
  hasData: boolean
  selectedProjectId: number | null
  canManage: boolean
  groupPage: number
  groupPages: number
  groupTotal: number
}>()

const emit = defineEmits<{
  'select-project': [id: number]
  'edit-project': [id: number]
  'complete-project': [id: number]
  'cancel-project': [id: number]
  search: [keyword: string]
  'add-project': []
  'status-change': [value: string]
  'update-group-page': [page: number]
}>()

/** 状态筛选选项（默认进行中） */
const STATUS_OPTIONS = [
  { value: 'in_progress', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
] as const

/** 当前状态筛选（默认进行中） */
const statusFilter = ref<string>('in_progress')

function onStatusChange(value: string) {
  statusFilter.value = value
  emit('status-change', value)
}

/**
 * 项目卡片高度（200px 缩略图 + 上下 8px 内边距 = 216px），
 * 加上卡片间距 6px 后作为虚拟滚动单个槽位高度。
 * 卡片内容均为单行截断，高度恒定，适合固定高度虚拟滚动。
 */
const PROJECT_CARD_H = 216
const PROJECT_CARD_SLOT_H = PROJECT_CARD_H + 6

// ==================== 分组选择与项目编号 ====================
const groupsRef = toRef(props, 'groups')
const selectedProjectIdRef = toRef(props, 'selectedProjectId')
const {
  selectedMakerKey,
  isMakerSelected,
  selectMaker,
  selectedGroup,
  projectDisplayNumbers,
} = useProjectGrouping(groupsRef, selectedProjectIdRef)

// ==================== 虚拟滚动容器高度测量 ====================
const { areaRef: projectAreaRef, height: projectAreaHeight, measure: measureProjectArea } = useVirtualAreaMeasure()
// VirtualList 为泛型组件，InstanceType 无法推导，用结构化类型描述所需句柄
const virtualListRef = ref<{ scrollToTop: () => void } | null>(null)

// groups 数据变化时（首次加载 / 新增后刷新 / 删除后刷新），
// 父级布局可能因 v-else 分支从"空状态"切换到"双栏布局"而高度变化，
// 此时主动触发一次测量，覆盖 ResizeObserver 在 0→非0 边界不触发的盲区。
watch(
  () => props.groups,
  () => {
    nextTick(() => nextTick(measureProjectArea))
  },
)

// 切换版师时回到列表顶部
watch(selectedMakerKey, () => {
  virtualListRef.value?.scrollToTop()
})

// ==================== 搜索 ====================
function onSearchInput(e: Event) {
  const target = e.target as HTMLInputElement
  emit('search', target.value)
}

// ==================== 缩略图加载状态与大图预览 ====================
/** 已加载清晰缩略图的项目 id 集合（驱动骨架屏/模糊图淡出与清晰图淡入）
 *  由父级持有：虚拟滚动销毁/重建行组件后仍保留淡入状态，避免骨架动画重放 */
const thumbLoaded = ref<Set<number>>(new Set())

/** 图片大图预览 URL */
const previewImage = ref<string | null>(null)

/** 打开图片大图预览 */
function openImagePreview(url: string) {
  previewImage.value = url
}

/** 清晰缩略图加载完成：记录状态，触发 blur-up 过渡 */
function onThumbLoad(projectId: number) {
  if (!thumbLoaded.value.has(projectId)) {
    thumbLoaded.value = new Set(thumbLoaded.value).add(projectId)
  }
}
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
  color: var(--color-text-primary);
  outline: none;
  box-sizing: border-box;
}

.cgl-search-input:focus {
  border-color: var(--color-primary-400);
}

/* 状态筛选胶囊 */
.cgl-status-filter {
  display: inline-flex;
  gap: 4px;
  padding: 4px 12px 0;
  flex-shrink: 0;
}

.cgl-status-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-secondary, #6b7280);
  background: transparent;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}

.cgl-status-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}

.cgl-status-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  border-color: var(--color-primary-200);
  font-weight: 600;
}

/* 分页栏 */
.cgl-container > :deep(.ui-pagination) {
  padding: 4px 12px;
  flex-shrink: 0;
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

/* 右侧：项目区域（虚拟滚动容器，不再自行滚动，滚动由 VirtualList 接管）
 * contain 限定重排范围，滚动时不影响左侧客户列与外部布局。 */
.cgl-project-area {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  padding: 8px;
  contain: layout;
}

.cgl-project-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-text-secondary, #9ca3af);
  font-size: 13px;
}

/* 虚拟滚动列表：滚动容器自身高度由 JS 测量注入 */
.cgl-virtual-list {
  height: 100%;
}
</style>

<!-- 非 scoped：Teleport 到 body 的图片模态框样式（与 product 页面共享） -->
<style>
.pd-overlay {
  position: fixed; inset: 0; z-index: 1050; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; padding: 16px;
}

.pd-modal {
  border-radius: 18px; border: none; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
  background: white; overflow: hidden;
}
.pd-modal-img-dialog { max-width: 90vw; width: 800px; }
.pd-modal-header {
  padding: 14px 20px; background: transparent;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  display: flex; justify-content: space-between; align-items: center;
}
.pd-modal-title { font-size: 14px; font-weight: 700; color: var(--color-text); }
.pd-modal-close {
  width: 32px; height: 32px; border-radius: 8px; border: none;
  background: var(--color-surface, #f8fafc); color: var(--color-text-secondary);
  display: flex; align-items: center; justify-content: center; font-size: 14px;
  transition: background 0.2s ease, color 0.2s ease; cursor: pointer;
}
.pd-modal-close:hover { background: var(--color-border-light, #e2e8f0); color: var(--color-text); }
.pd-modal-body {
  padding: 20px; background: var(--color-surface, #f8fafc);
  display: flex; align-items: center; justify-content: center; min-height: 50vh;
}
.pd-modal-img-view {
  max-width: 100%; max-height: 80vh; object-fit: contain;
  border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}
</style>

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
            <div
              :class="['cgl-project-card', { active: selectedProjectId === proj.id, 'is-completed': proj.status === 'completed' }]"
              role="button"
              tabindex="0"
              @click="$emit('select-project', proj.id)"
              @keyup.enter="$emit('select-project', proj.id)"
            >
              <div class="cgl-card-left">
                <div
                  v-if="proj.product_image_url"
                  class="cgl-card-thumb"
                  :class="{ 'is-loaded': thumbLoaded.has(proj.id) }"
                  role="button"
                  title="点击查看大图"
                  @click.stop="openImagePreview(proj.product_image_url!)"
                >
                  <!-- 骨架屏：图片加载完成前显示微光动画占位 -->
                  <div class="cgl-thumb-skeleton" aria-hidden="true" />
                  <!-- 模糊占位图（32px，blur-up）：滚动即见，清晰图加载后淡出 -->
                  <img
                    v-if="proj.product_image_blur_url"
                    :src="proj.product_image_blur_url"
                    class="cgl-thumb-blur"
                    alt=""
                    aria-hidden="true"
                    decoding="async"
                    fetchpriority="low"
                  />
                  <!-- 清晰缩略图：加载完成后淡入 -->
                  <img
                    :src="proj.product_image_thumbnail_url || proj.product_image_url"
                    class="cgl-thumb-img"
                    alt=""
                    width="200"
                    height="200"
                    loading="lazy"
                    decoding="async"
                    fetchpriority="low"
                    @error="onThumbError($event, proj)"
                    @load="onThumbLoad(proj.id)"
                  />
                  <span v-if="proj.status === 'completed'" class="cgl-card-status-badge">
                    <i class="fas fa-check-circle" aria-hidden="true" /> 已完成
                  </span>
                </div>
                <div v-else class="cgl-card-thumb cgl-card-thumb-placeholder">
                  <i class="fas fa-tshirt" aria-hidden="true" />
                  <span v-if="proj.status === 'completed'" class="cgl-card-status-badge">
                    <i class="fas fa-check-circle" aria-hidden="true" /> 已完成
                  </span>
                </div>
              </div>
              <div class="cgl-card-right">
                <div class="cgl-card-info">
                  <div class="cgl-card-line">
                    <span class="cgl-card-label">时间：</span>
                    <span class="cgl-card-value">{{ formatTime(proj.updated_at) }}</span>
                  </div>
                  <div class="cgl-card-line">
                    <span class="cgl-card-label">名称：</span>
                    <span class="cgl-card-value">{{ proj.product_name }}</span>
                  </div>
                  <div class="cgl-card-line">
                    <span class="cgl-card-label">版师：</span>
                    <span class="cgl-card-value">{{ selectedGroup?.pattern_maker_name || '-' }}</span>
                  </div>
                  <div class="cgl-card-line">
                    <span class="cgl-card-label">编号：</span>
                    <span class="cgl-card-value">{{ projectDisplayNumbers.get(proj.id) }}</span>
                  </div>
                </div>
                <div v-if="canManage" class="cgl-card-actions">
                  <button
                    type="button"
                    class="cgl-card-action cgl-card-action--edit"
                    title="编辑该打样项目"
                    @click.stop="$emit('edit-project', proj.id)"
                  >
                    <i class="fas fa-pen" aria-hidden="true" /> 编辑
                  </button>
                  <button
                    v-if="proj.status === 'in_progress'"
                    type="button"
                    class="cgl-card-action cgl-card-action--done"
                    title="标记为已完成"
                    @click.stop="$emit('complete-project', proj.id)"
                  >
                    <i class="fas fa-check" aria-hidden="true" /> 完成
                  </button>
                  <button
                    v-if="proj.status === 'in_progress'"
                    type="button"
                    class="cgl-card-action cgl-card-action--cancel"
                    title="取消该打样项目"
                    @click.stop="$emit('cancel-project', proj.id)"
                  >
                    <i class="fas fa-times" aria-hidden="true" /> 取消
                  </button>
                </div>
              </div>
            </div>
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
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import EmptyState from './EmptyState.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import { resolveStaticUrl } from '@/api/request'
import type { PatternMakerGroup, ProjectSummary } from '@/api/patternRoom'

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

/** 当前选中的版师 key */
const selectedMakerKey = ref<string | null>(null)

function groupKey(makerId: number | null): string {
  return makerId != null ? String(makerId) : '_unassigned'
}

function isMakerSelected(makerId: number | null): boolean {
  return selectedMakerKey.value === groupKey(makerId)
}

function selectMaker(makerId: number | null) {
  selectedMakerKey.value = groupKey(makerId)
}

/** 当前选中的分组 */
const selectedGroup = computed(() => {
  if (!selectedMakerKey.value) return null
  return props.groups.find((g) => groupKey(g.pattern_maker_id) === selectedMakerKey.value) ?? null
})

// ==================== 虚拟滚动容器高度测量 ====================
const projectAreaRef = ref<HTMLElement | null>(null)
/**
 * 容器高度。初始为 0，模板靠 `v-else-if="projectAreaHeight > 0"` 守卫 VirtualList 渲染。
 * 由于父级 flex 链可能在数据加载后才完成布局，单次 onMounted 测量经常得到 0，
 * 这里采用多策略保证最终能拿到正确高度：
 *   1. onMounted 同步测量（best-effort）
 *   2. nextTick 后再次测量（父级 v-if/v-else 切换后）
 *   3. requestAnimationFrame 后测量（最终布局稳定）
 *   4. 监听自身 + 父级尺寸变化（ResizeObserver，仅在变化时触发）
 *   5. 监听 window resize（视口变化）
 *   6. 监听 groups 数据变化（分组重新渲染可能影响布局）
 */
const projectAreaHeight = ref(0)
// VirtualList 为泛型组件，InstanceType 无法推导，用结构化类型描述所需句柄
const virtualListRef = ref<{ scrollToTop: () => void } | null>(null)

let areaResizeObserver: ResizeObserver | null = null
let parentResizeObserver: ResizeObserver | null = null
let windowResizeHandler: (() => void) | null = null

function measureProjectArea() {
  if (!projectAreaRef.value) return
  // getBoundingClientRect 比 clientHeight 更可靠：不受 box-sizing 影响
  const rect = projectAreaRef.value.getBoundingClientRect()
  // 使用 offsetHeight 优先（已包含 padding），若为 0 则降级到 rect.height
  const h = projectAreaRef.value.offsetHeight || Math.round(rect.height)
  if (h > 0 && h !== projectAreaHeight.value) {
    projectAreaHeight.value = h
  }
}

function tryMeasureWithRetry() {
  // 同步测量（此时通常 onMounted 刚执行）
  measureProjectArea()
  if (projectAreaHeight.value > 0) return
  // nextTick 后再试（父级 v-if/v-else 切换可能影响布局）
  nextTick(() => {
    measureProjectArea()
    if (projectAreaHeight.value > 0) return
    // rAF 后再试（最终布局稳定阶段）
    requestAnimationFrame(() => {
      measureProjectArea()
    })
  })
}

onMounted(() => {
  tryMeasureWithRetry()
  if (projectAreaRef.value && typeof ResizeObserver !== 'undefined') {
    areaResizeObserver = new ResizeObserver(measureProjectArea)
    areaResizeObserver.observe(projectAreaRef.value)
    // 同时监听父级（cgl-body / pr-left-pane）尺寸变化，
    // 解决父级从 0 → 有数据时自身尺寸可能不变导致漏触发的问题
    // 只需追踪最近一层 flex 父级即可，过深会增加无意义的回调
    const parent = projectAreaRef.value.parentElement
    if (parent) {
      parentResizeObserver = new ResizeObserver(measureProjectArea)
      parentResizeObserver.observe(parent)
    }
  }
  // 监听 window resize（窄屏/宽屏切换、抽屉展开/收起等场景）
  windowResizeHandler = () => {
    // rAF 延迟，避免 resize 期间反复触发
    requestAnimationFrame(measureProjectArea)
  }
  window.addEventListener('resize', windowResizeHandler)
})

onUnmounted(() => {
  areaResizeObserver?.disconnect()
  parentResizeObserver?.disconnect()
  if (windowResizeHandler) {
    window.removeEventListener('resize', windowResizeHandler)
    windowResizeHandler = null
  }
})

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

/** 按日期生成递增编号：YYYYMMDD + 两位序号（同天内按 updated_at 顺序递增） */
const projectDisplayNumbers = computed(() => {
  const group = selectedGroup.value
  if (!group) return new Map<number, string>()

  const sorted = [...group.projects].sort((a, b) => {
    const ta = new Date(a.updated_at).getTime()
    const tb = new Date(b.updated_at).getTime()
    if (ta !== tb) return ta - tb
    return a.id - b.id
  })

  const counter = new Map<string, number>()
  const result = new Map<number, string>()

  for (const proj of sorted) {
    const dateKey = proj.updated_at.slice(0, 10)
    const dateNum = dateKey.replace(/-/g, '')
    const next = (counter.get(dateKey) ?? 0) + 1
    counter.set(dateKey, next)
    result.set(proj.id, `${dateNum}${String(next).padStart(2, '0')}`)
  }

  return result
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

/** 已加载清晰缩略图的项目 id 集合（驱动骨架屏/模糊图淡出与清晰图淡入） */
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

/**
 * 缩略图加载失败时回退到原图。
 * - 历史数据（缩略图未生成）会出现 404，需要回退
 * - 设置 data-fallback 标记位防止反复重试；回退图加载成功同样触发淡入
 */
function onThumbError(e: Event, proj: { product_image_url?: string | null }) {
  const img = e.target as HTMLImageElement
  if (img.dataset.fallback || !proj.product_image_url) {
    img.src = ''
    return
  }
  img.dataset.fallback = '1'
  img.src = proj.product_image_url
}

// 默认选中第一个分组
watch(
  () => props.groups,
  (g) => {
    if (g && g.length > 0 && selectedMakerKey.value === null) {
      selectedMakerKey.value = groupKey(g[0]!.pattern_maker_id)
    }
  },
  { immediate: true },
)

// 选中项目变化时，自动切换到包含该项目的版师分组
// 场景：新增项目后选中新项目，但新项目所属版师与当前选中分组不同，
// 若不切换分组，右侧卡片区域看不到新项目。
watch(
  () => props.selectedProjectId,
  (newId) => {
    if (newId == null) return
    // 当前分组已包含该项目，无需切换
    if (selectedGroup.value?.projects.some((p) => p.id === newId)) return
    // 查找包含该项目的分组并切换
    const targetGroup = props.groups.find((g) => g.projects.some((p) => p.id === newId))
    if (targetGroup) {
      selectedMakerKey.value = groupKey(targetGroup.pattern_maker_id)
    }
  },
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

/* 项目卡片（固定高度，配合虚拟滚动） */
.cgl-project-card {
  display: flex;
  gap: 10px;
  width: 100%;
  height: 216px;
  margin-bottom: 6px;
  padding: 8px;
  box-sizing: border-box;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
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
  position: relative;
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

/* 骨架屏：微光扫过动画，清晰图加载完成后淡出 */
.cgl-thumb-skeleton {
  position: absolute;
  inset: 0;
  z-index: 1;
  background: linear-gradient(100deg, #f1f5f9 40%, #e2e8f0 50%, #f1f5f9 60%);
  background-size: 200% 100%;
  animation: cgl-shimmer 1.4s linear infinite;
  opacity: 1;
  transition: opacity 0.3s ease;
}

.cgl-card-thumb.is-loaded .cgl-thumb-skeleton {
  opacity: 0;
}

@keyframes cgl-shimmer {
  0% { background-position: 120% 0; }
  100% { background-position: -120% 0; }
}

/* 模糊占位图（blur-up）：铺满 + CSS 模糊放大，清晰图加载后淡出 */
.cgl-thumb-blur {
  position: absolute;
  inset: 0;
  z-index: 2;
  width: 100%;
  height: 100%;
  object-fit: cover;
  filter: blur(10px);
  transform: scale(1.15);
  opacity: 1;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.cgl-card-thumb.is-loaded .cgl-thumb-blur {
  opacity: 0;
}

/* 清晰缩略图：默认透明，加载完成后淡入（避免占位闪烁） */
.cgl-thumb-img {
  position: relative;
  z-index: 3;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  transition: opacity 0.3s ease;
}

.cgl-card-thumb.is-loaded .cgl-thumb-img {
  opacity: 1;
}

.cgl-card-thumb-placeholder i {
  font-size: 48px;
  color: var(--color-text-secondary);
  opacity: 0.5;
}

/* 已完成角标（叠加在缩略图右上角） */
.cgl-card-status-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 4;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(22, 163, 74, 0.92);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.6;
  pointer-events: none;
}

/* 已完成卡片：绿色边框 */
.cgl-project-card.is-completed {
  border-color: #22c55e40;
}
.cgl-project-card.is-completed.active {
  border-color: #16a34a;
}

.cgl-card-right {
  flex: 1;
  min-width: 0;
}

.cgl-card-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cgl-card-line {
  display: flex;
  align-items: baseline;
  gap: 4px;
  font-size: 13px;
  line-height: 1.5;
}

.cgl-card-label {
  flex-shrink: 0;
  color: var(--color-text-secondary);
}

.cgl-card-value {
  min-width: 0;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 卡片操作按钮（编辑 / 完成） */
.cgl-card-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.cgl-card-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 6px;
  background: #fff;
  font-size: 12px;
  color: var(--color-text-primary);
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}

.cgl-card-action:hover {
  border-color: #ff9f43;
  color: #ff9f43;
  background: #ff9f4308;
}

.cgl-card-action--done:hover {
  border-color: #16a34a;
  color: #16a34a;
  background: #16a34a0a;
}

.cgl-card-action--cancel:hover {
  border-color: #ef4444;
  color: #ef4444;
  background: #ef44440a;
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

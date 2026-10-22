<template>
  <div class="cgl-project-area">
    <div v-if="!selectedGroup" class="cgl-project-empty">
      <span>请选择一个版师</span>
    </div>
    <div v-else-if="selectedGroup.projects.length === 0" class="cgl-project-empty">
      <span>该版师暂无项目</span>
    </div>
    <template v-else>
      <div
        ref="projectAreaRef"
        class="cgl-list-scroll"
        :style="{ [CSS_VAR_CARD_H]: DEFAULT_CARD_H + 'px' }"
      >
        <VirtualList
          v-if="projectAreaHeight > 0"
          ref="virtualListRef"
          :items="pageProjects"
          :item-height="projectCardSlotH"
          :container-height="projectAreaHeight"
          :item-key="(p: ProjectSummary) => p.id"
          class="cgl-virtual-list"
        >
          <template #default="{ item: proj }">
            <ProjectCardItem
              v-memo="[proj.id, proj.updated_at, proj.status, proj.product_name, proj.product_image_url, proj.product_image_thumbnail_url, proj.product_image_blur_url, selectedProjectId === proj.id, projectDisplayNumbers.get(proj.id), canManage, selectedGroup?.pattern_maker_name]"
              :proj="proj"
              :selected="selectedProjectId === proj.id"
              :maker-name="selectedGroup?.pattern_maker_name"
              :display-number="projectDisplayNumbers.get(proj.id)"
              :can-manage="canManage"
              @select="$emit('select-project', $event)"
              @preview="$emit('preview', $event)"
              @edit="$emit('edit-project', $event)"
              @complete="$emit('complete-project', $event)"
              @cancel="$emit('cancel-project', $event)"
            />
          </template>
        </VirtualList>
        <!-- 该分支只在「容器高度尚未测出」时短暂出现，等价于正在加载。
             live region 必须常驻：用 v-if 包住会让它变成「新节点出现」，
             部分读屏器不会播报，正好漏掉首次加载这一场景（审查 A11Y-13 硬契约 1）。 -->
        <UiLoadingStatus :loading="projectAreaHeight <= 0" label="加载中…" />
      </div>
      <!-- 组内项目分页：分组项目较多时（如单版师上千条）按页加载渲染，避免一次渲染全部 -->
      <UiPagination
        v-if="totalItems > PROJECT_PAGE_SIZE"
        v-model:current-page="projectPage"
        :total-pages="projectPages"
        :total-items="totalItems"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import UiLoadingStatus from '@/components/ui/UiLoadingStatus.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import VirtualList from '@/components/ui/VirtualList.vue'
import ProjectCardItem from './ProjectCardItem.vue'
import type { PatternMakerGroup, ProjectSummary } from '@/api/patternRoom'
import { useVirtualAreaMeasure } from '../composables/useVirtualAreaMeasure'

const props = defineProps<{
  selectedGroup: PatternMakerGroup | null
  selectedProjectId: number | null
  canManage: boolean
  groups: PatternMakerGroup[]
  selectedMakerKey: string | null
  projectDisplayNumbers: Map<number, string>
}>()

defineEmits<{
  'select-project': [id: number]
  'edit-project': [id: number]
  'complete-project': [id: number]
  'cancel-project': [id: number]
  preview: [url: string]
}>()

/** 卡片高度单一事实来源：DEFAULT_CARD_H 是唯一字面量，经模板 :style 注入 CSS 变量，
 *  ProjectCardItem 与本组件运行时读取消费同一来源，改高度只需改此处 */
const CSS_VAR_CARD_H = '--pr-card-h'
const DEFAULT_CARD_H = 256
/** 卡片之间的垂直间距，必须与 ProjectCardItem 的 .cgl-project-card margin-bottom 保持一致 */
const CARD_GAP = 10
/** 卡片槽位高度（卡片高 + 卡片间距） */
const projectCardSlotH = ref(DEFAULT_CARD_H + CARD_GAP)

function readCardSlotH(): number {
  const el = projectAreaRef.value
  if (!el) return DEFAULT_CARD_H + CARD_GAP
  const h = Number.parseFloat(getComputedStyle(el).getPropertyValue(CSS_VAR_CARD_H))
  return (Number.isFinite(h) && h > 0 ? h : DEFAULT_CARD_H) + CARD_GAP
}
/** 组内项目分页每页条数 */
const PROJECT_PAGE_SIZE = 20

const { areaRef: projectAreaRef, height: projectAreaHeight, measure: measureProjectArea } = useVirtualAreaMeasure()
const virtualListRef = ref<{ scrollToTop: () => void } | null>(null)

onMounted(() => {
  // 挂载后 CSS 变量已可解析，读取真实卡片槽位高度
  projectCardSlotH.value = readCardSlotH()
})

/** 组内项目分页状态：切换版师分组时重置回第 1 页 */
const projectPage = ref(1)
const totalItems = computed(() => props.selectedGroup?.projects.length ?? 0)
const projectPages = computed(() => Math.max(1, Math.ceil(totalItems.value / PROJECT_PAGE_SIZE)))
const pageProjects = computed(() => {
  const all = props.selectedGroup?.projects ?? []
  const start = (projectPage.value - 1) * PROJECT_PAGE_SIZE
  return all.slice(start, start + PROJECT_PAGE_SIZE)
})

watch(
  () => props.groups,
  () => {
    nextTick(() => {
      // 卡片高度来自 CSS 变量，布局稳定后重读一次
      projectCardSlotH.value = readCardSlotH()
      requestAnimationFrame(measureProjectArea)
    })
  },
)

watch(
  () => props.selectedMakerKey,
  () => {
    projectPage.value = 1
    virtualListRef.value?.scrollToTop()
  },
)

// 数据更新后分页数可能缩减（如删除项目），越界时收敛回最后一页
watch(projectPages, (pages) => {
  if (projectPage.value > pages) {
    projectPage.value = pages
  }
})

// 选中项目不在当前页时（如从搜索/编辑流程跳回），自动跳到其所在页
watch(
  () => props.selectedProjectId,
  (id) => {
    if (id == null) return
    const all = props.selectedGroup?.projects ?? []
    const idx = all.findIndex((p) => p.id === id)
    if (idx === -1) return
    const page = Math.floor(idx / PROJECT_PAGE_SIZE) + 1
    if (page !== projectPage.value) {
      projectPage.value = page
    }
  },
)

// 翻页时重置虚拟列表滚动位置，避免滚动偏移残留导致空白/错位
watch(projectPage, () => {
  virtualListRef.value?.scrollToTop()
})
</script>

<style scoped>
.cgl-project-area {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 8px;
  contain: layout;
}
/* --pr-card-h 由模板 :style 注入（DEFAULT_CARD_H 唯一字面量），此处不再定义 */
.cgl-list-scroll {
  flex: 1;
  min-height: 0;
}
.cgl-project-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--color-text-secondary, #9ca3af);
  font-size: 13px;
}
.cgl-virtual-list {
  height: 100%;
}
</style>
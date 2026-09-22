<template>
  <div class="cgl-project-area">
    <div v-if="!selectedGroup" class="cgl-project-empty">
      <span>请选择一个版师</span>
    </div>
    <div v-else-if="selectedGroup.projects.length === 0" class="cgl-project-empty">
      <span>该版师暂无项目</span>
    </div>
    <template v-else>
      <div ref="projectAreaRef" class="cgl-list-scroll">
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
              @click="$emit('select-project', proj.id)"
              @keyup.enter="$emit('select-project', proj.id)"
              @preview="$emit('preview', $event)"
              @edit="$emit('edit-project', $event)"
              @complete="$emit('complete-project', $event)"
              @cancel="$emit('cancel-project', $event)"
            />
          </template>
        </VirtualList>
        <div v-else class="cgl-project-empty" aria-live="polite">
          <UiSpinner size="sm" />
          <span>加载中...</span>
        </div>
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
import UiSpinner from '@/components/ui/UiSpinner.vue'
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

/** 卡片高度单一事实来源：CSS 变量 --pr-card-h（ProjectCardItem 同步消费），
 *  JS 侧运行时读取，改样式无需同步两处常量 */
const CSS_VAR_CARD_H = '--pr-card-h'
/** 卡片 CSS 高度默认值（与 ProjectCardItem 样式中的回退值保持一致） */
const DEFAULT_CARD_H = 216
/** 卡片槽位高度（卡片高 + margin-bottom 6px） */
const projectCardSlotH = ref(DEFAULT_CARD_H + 6)

function readCardSlotH(): number {
  const el = projectAreaRef.value
  if (!el) return DEFAULT_CARD_H + 6
  const h = Number.parseFloat(getComputedStyle(el).getPropertyValue(CSS_VAR_CARD_H))
  return (Number.isFinite(h) && h > 0 ? h : DEFAULT_CARD_H) + 6
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
/* 卡片高度单一事实来源：ProjectCardItem 通过 var(--pr-card-h) 消费（scoped 变量随 DOM 属性下传） */
.cgl-list-scroll {
  --pr-card-h: 216px;
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
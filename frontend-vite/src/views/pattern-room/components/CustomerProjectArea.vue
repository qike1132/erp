<template>
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
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
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

const PROJECT_CARD_H = 216
const PROJECT_CARD_SLOT_H = PROJECT_CARD_H + 6

const { areaRef: projectAreaRef, height: projectAreaHeight, measure: measureProjectArea } = useVirtualAreaMeasure()
const virtualListRef = ref<{ scrollToTop: () => void } | null>(null)

watch(
  () => props.groups,
  () => {
    nextTick(() => requestAnimationFrame(measureProjectArea))
  },
)

watch(
  () => props.selectedMakerKey,
  () => {
    virtualListRef.value?.scrollToTop()
  },
)
</script>

<style scoped>
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
.cgl-virtual-list {
  height: 100%;
}
</style>
<template>
  <div class="cgl-container">
    <CustomerGroupSearchBar
      status-filter="in_progress"
      @search="$emit('search', $event)"
      @status-change="$emit('status-change', $event)"
    />

    <div v-if="loading" class="cgl-loading">
      <UiSpinner size="sm" />
      <span>加载中...</span>
    </div>

    <EmptyState
      v-else-if="!hasData"
      icon="fas fa-boxes"
      title="暂无打样项目"
      description="点击右上角「新增打样项目」创建第一个项目"
    />

    <div v-else class="cgl-body">
      <CustomerMakerPanel
        :groups="groups"
        :is-maker-selected="isMakerSelected"
        :select-maker="selectMaker"
      />
      <CustomerProjectArea
        :selected-group="selectedGroup"
        :selected-project-id="selectedProjectId"
        :can-manage="canManage"
        :thumb-loaded="thumbLoaded"
        :groups="groups"
        :selected-maker-key="selectedMakerKey"
        :project-display-numbers="projectDisplayNumbers"
        @select-project="$emit('select-project', $event)"
        @edit-project="$emit('edit-project', $event)"
        @complete-project="$emit('complete-project', $event)"
        @cancel-project="$emit('cancel-project', $event)"
        @preview="openImagePreview"
        @thumb-load="onThumbLoad"
      />
    </div>

    <UiPagination
      v-if="groupPages > 1"
      :current-page="groupPage"
      :total-pages="groupPages"
      :total-items="groupTotal"
      @update:current-page="$emit('update-group-page', $event)"
    />

    <ImagePreviewModal v-model:image="previewImage" />
  </div>
</template>

<script setup lang="ts">
import { ref, toRef } from 'vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import EmptyState from './EmptyState.vue'
import CustomerGroupSearchBar from './CustomerGroupSearchBar.vue'
import CustomerMakerPanel from './CustomerMakerPanel.vue'
import CustomerProjectArea from './CustomerProjectArea.vue'
import ImagePreviewModal from './ImagePreviewModal.vue'
import type { PatternMakerGroup } from '@/api/patternRoom'
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

defineEmits<{
  'select-project': [id: number]
  'edit-project': [id: number]
  'complete-project': [id: number]
  'cancel-project': [id: number]
  search: [keyword: string]
  'add-project': []
  'status-change': [value: string]
  'update-group-page': [page: number]
}>()

const groupsRef = toRef(props, 'groups')
const selectedProjectIdRef = toRef(props, 'selectedProjectId')
const {
  selectedMakerKey,
  isMakerSelected,
  selectMaker,
  selectedGroup,
  projectDisplayNumbers,
} = useProjectGrouping(groupsRef, selectedProjectIdRef)

const thumbLoaded = ref<Set<number>>(new Set())
const previewImage = ref<string | null>(null)

function openImagePreview(url: string) {
  previewImage.value = url
}

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
.cgl-container > :deep(.ui-pagination) {
  padding: 4px 12px;
  flex-shrink: 0;
}
.cgl-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 40px 0;
  color: var(--color-text-secondary, #9ca3af);
  font-size: 13px;
}
.cgl-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}
</style>

<template>
  <div class="cgl-container">
    <CustomerGroupSearchBar
      :status-filter="statusFilter"
      :can-manage="canManage"
      @search="$emit('search', $event)"
      @status-change="$emit('status-change', $event)"
      @add-project="$emit('add-project')"
    />

    <!--
      加载态走 UiLoadingStatus（常驻 live region，读屏器能听到「加载中」）。
      注意不能再用 v-if 包住它 —— 容器必须一直在树里（审查 A11Y-13）。
    -->
    <UiLoadingStatus :loading="loading" label="加载中…" />

    <EmptyState
      v-if="!loading && !hasData"
      icon="boxes"
      title="暂无打样项目"
      description="点击上方「新建打样」创建第一个项目"
    />

    <div v-else-if="!loading" class="cgl-body">
      <CustomerMakerPanel
        :groups="groups"
        :is-maker-selected="isMakerSelected"
        :select-maker="selectMaker"
      />
      <CustomerProjectArea
        :selected-group="selectedGroup"
        :selected-project-id="selectedProjectId"
        :can-manage="canManage"
        :groups="groups"
        :selected-maker-key="selectedMakerKey"
        :project-display-numbers="projectDisplayNumbers"
        @select-project="$emit('select-project', $event)"
        @edit-project="$emit('edit-project', $event)"
        @complete-project="$emit('complete-project', $event)"
        @cancel-project="$emit('cancel-project', $event)"
        @preview="openImagePreview"
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
import UiLoadingStatus from '@/components/ui/UiLoadingStatus.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import EmptyState from './EmptyState.vue'
import CustomerGroupSearchBar from './CustomerGroupSearchBar.vue'
import CustomerMakerPanel from './CustomerMakerPanel.vue'
import CustomerProjectArea from './CustomerProjectArea.vue'
import ImagePreviewModal from '@/components/ui/ImagePreviewModal.vue'
import type { PatternMakerGroup, ProjectStatus } from '@/api/patternRoom'
import { useProjectGrouping } from '../composables/useProjectGrouping'

const props = defineProps<{
  groups: PatternMakerGroup[]
  loading: boolean
  hasData: boolean
  selectedProjectId: number | null
  canManage: boolean
  /** 当前状态筛选（透传给搜索栏做受控高亮） */
  statusFilter: ProjectStatus
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
  'status-change': [value: ProjectStatus]
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

const previewImage = ref<string | null>(null)

function openImagePreview(url: string) {
  previewImage.value = url
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
  padding: 2px 8px;
  flex-shrink: 0;
}
/* 加载态外观由 UiLoadingStatus 自身承载（原先的 .cgl-loading 已移除） */
.cgl-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}
</style>

<template>
  <div class="bk-col-content">
    <BackupDbOverview :tables="tables" :loading="tablesLoading" />

    <BackupModeSwitch :model-value="backupMode" @change="emit('mode-change', $event)" />

    <BackupActionButtons
      :backup-mode="backupMode"
      :backup-remark="backupRemark"
      :exporting="exporting"
      :saving-to-server="savingToServer"
      :saving-incremental="savingIncremental"
      @update:backup-remark="emit('update:backupRemark', $event)"
      @export="emit('export')"
      @save-to-server="emit('save-to-server')"
      @save-incremental="emit('save-incremental')"
    />

    <BackupSaveResultCard v-if="saveResult" :result="saveResult" />
  </div>
</template>

<script setup lang="ts">
import BackupDbOverview from './BackupDbOverview.vue'
import BackupModeSwitch from './components/BackupModeSwitch.vue'
import BackupActionButtons from './components/BackupActionButtons.vue'
import BackupSaveResultCard from './BackupSaveResultCard.vue'

export interface BackupSaveResult {
  filename: string
  size: number
  format: string
  table_count: number
  total_rows: number
  includes?: {
    filestore_count?: number
    config_files?: string[]
    redis_rdb?: boolean
  }
}

defineProps<{
  tables: { name: string; rows: number }[]
  tablesLoading: boolean
  backupMode: 'custom' | 'default'
  backupRemark: string
  exporting: boolean
  savingToServer: boolean
  savingIncremental: boolean
  saveResult: BackupSaveResult | null
}>()

const emit = defineEmits<{
  (e: 'update:backupRemark', value: string): void
  (e: 'mode-change', mode: 'custom' | 'default'): void
  (e: 'export'): void
  (e: 'save-to-server'): void
  (e: 'save-incremental'): void
}>()
</script>

<style scoped>
.bk-col-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}
</style>

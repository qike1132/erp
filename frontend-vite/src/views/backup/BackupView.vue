<template>
  <div class="bk-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <div class="bk-card-title-group">
          <div class="bk-icon-box bk-icon-blue">
            <FontAwesomeIcon icon="database" />
          </div>
          <div>
            <h3>数据备份与恢复</h3>
            <small>备份系统全部数据，或从备份文件恢复</small>
          </div>
        </div>
      </div>

      <!-- Tab bar -->
      <div class="bk-tab-bar">
        <div class="bk-tab-group">
          <button
            class="bk-tab-btn"
            :class="{ 'bk-tab-active': activeTab === 'backup' }"
            @click="handleTabChange('backup')"
          >
            <FontAwesomeIcon icon="database" /> 备份与恢复
          </button>
          <button
            class="bk-tab-btn"
            :class="{ 'bk-tab-active': activeTab === 'records' }"
            @click="handleTabChange('records')"
          >
            <FontAwesomeIcon icon="history" /> 备份记录
          </button>
        </div>
        <div class="bk-tab-actions">
          <button
            class="bk-action-btn bk-action-secondary"
            :disabled="checking"
            @click="handleIntegrityCheck"
            title="备份完整性巡检"
          >
            <UiLoadingIcon :loading="checking" icon="shield-alt" />
            {{ checking ? '巡检中...' : '完整性巡检' }}
          </button>
        </div>
      </div>

      <!-- Integrity check result -->
      <IntegrityCheckPanel :check-result="checkResult" @close="checkResult = null" />

      <div v-show="activeTab === 'backup'" class="bk-body">
        <!-- 左栏：一键备份 -->
        <div class="bk-col">
          <div class="bk-col-title"><FontAwesomeIcon icon="download" /> 一键备份</div>
          <BackupModeSelector
            :tables="tables"
            :tables-loading="tablesLoading"
            :backup-mode="backupMode"
            :backup-remark="backupRemark"
            :exporting="exporting"
            :saving-to-server="savingToServer"
            :saving-incremental="savingIncremental"
            :save-result="saveResult"
            @update:backup-remark="backupRemark = $event"
            @mode-change="handleModeChange"
            @export="handleExport"
            @save-to-server="handleSaveToServer"
            @save-incremental="handleSaveIncremental"
          />
        </div>

        <!-- 右栏 -->
        <div class="bk-col">
          <!-- 自定义路径模式：文件上传恢复 -->
          <template v-if="backupMode === 'custom'">
            <div class="bk-col-title"><FontAwesomeIcon icon="upload" /> 一键恢复</div>
            <FileRestorePanel
              :selected-file="selectedFile"
              :validation-result="validationResultTyped"
              :importing="importing"
              :restore-result="restoreResultTyped"
              :restore-task-id="restoreTaskId"
              :missing-tables="missingTables"
              @file-select="setFile"
              @file-clear="clearFile"
              @restore="handleRestore"
              @restore-completed="onRestoreProgressCompleted"
              @restore-failed="onRestoreProgressFailed"
            />
          </template>

          <!-- 默认路径模式：服务器备份列表（子组件化，模板原样搬移） -->
          <ServerBackupList
            v-if="backupMode === 'default'"
            :backups="serverBackups"
            :loading="serverBackupsLoading"
            :restoring-file="restoringFile"
            :deleting-file="deletingFile"
            :backup-mode="backupMode"
            :restore-task-id="restoreTaskId"
            @restore="handleServerRestore"
            @delete="handleServerDelete"
            @restore-completed="onRestoreProgressCompleted"
            @restore-failed="onRestoreProgressFailed"
          />
        </div>
      </div>

      <!-- Records tab -->
      <div v-show="activeTab === 'records'" class="bk-records-body">
        <div class="bk-records-content">
          <BackupRecordList
            :records="records"
            :total="recordsTotal"
            :page="recordsPage"
            :page-size="recordsPageSize"
            :loading="recordsLoading"
            @page-change="loadRecords"
          />
        </div>
      </div>
    </div>

    <!-- 确认恢复弹窗（子组件化，模板原样搬移） -->
    <RestoreConfirmDialog
      v-model:open="showConfirmDialog"
      :confirm-target="confirmTarget"
      :importing="importing"
      :restoring-file="restoringFile"
      :restore-phase="restorePhase"
      @confirm="confirmRestoreAction"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import BackupRecordList from '@/components/backup/BackupRecordList.vue'
import BackupModeSelector from '@/components/backup/BackupModeSelector.vue'
import FileRestorePanel from '@/components/backup/FileRestorePanel.vue'
import IntegrityCheckPanel from '@/components/backup/IntegrityCheckPanel.vue'
import ServerBackupList from './components/ServerBackupList.vue'
import RestoreConfirmDialog from './components/RestoreConfirmDialog.vue'
import { useBackupCenter } from './composables/useBackupCenter'
import type { RestoreResult } from '@/components/backup/composables/useRestorePolling'
import type { BackupValidationResult } from '@/components/backup/FileRestorePanel.vue'

// 全部业务逻辑（备份导出 / 服务器备份 / 文件恢复 / 增量 / 记录 / 巡检）抽至 composables/useBackupCenter.ts
const {
  tables, tablesLoading,
  backupMode, backupRemark, handleModeChange, exporting, handleExport,
  savingToServer, saveResult, handleSaveToServer, savingIncremental, handleSaveIncremental,
  selectedFile, validationResult, importing, restoreResult, restorePhase, restoreTaskId,
  setFile, clearFile, missingTables, handleRestore,
  serverBackups, serverBackupsLoading, restoringFile, deletingFile,
  handleServerRestore, handleServerDelete,
  showConfirmDialog, confirmTarget, confirmRestoreAction,
  onRestoreProgressCompleted, onRestoreProgressFailed,
  records, recordsTotal, recordsPage, recordsPageSize, recordsLoading, loadRecords,
  checking, checkResult, handleIntegrityCheck,
} = useBackupCenter()

// 类型断言：useBackupCenter 返回可选属性，FileRestorePanel 期望非可选属性（模板中已用 ?. 兜底）
const restoreResultTyped = computed(() => restoreResult.value as Required<RestoreResult> | null)
const validationResultTyped = computed(() => validationResult.value as BackupValidationResult | null)

// --- Tab 切换 ---
const activeTab = ref<'backup' | 'records'>('backup')

function handleTabChange(tab: 'backup' | 'records') {
  activeTab.value = tab
  if (tab === 'records' && !records.value.length) {
    loadRecords()
  }
}
</script>

<style scoped>
/* === Layout === */
.bk-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Header === */
.bk-card-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.bk-card-title-group h3 {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}

.bk-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* === Icon Box === */
.bk-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}

.bk-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* === Body (Two columns) === */
.bk-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* === Column === */
.bk-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.bk-col + .bk-col {
  border-left: 1px solid var(--color-border-light);
}

.bk-col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.bk-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}

/* === Tab Bar === */
.bk-tab-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 20px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.bk-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}

.bk-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}

.bk-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.bk-tab-active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91,141,239,0.2);
  transform: translateY(-1px);
}

.bk-tab-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

/* === Action Buttons (for integrity check button in tab bar) === */
.bk-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 12px 18px;
  border: 2px solid var(--color-border-light);
  border-radius: var(--radius-button);
  background: white;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
}

.bk-action-secondary {
  background: var(--color-neutral-100);
  color: var(--color-neutral-700);
  border: 1px solid var(--color-border-light);
  margin-top: 8px;
}

.bk-action-secondary:hover:not(:disabled) {
  background: var(--color-neutral-200);
}

.bk-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

/* === Records Body === */
.bk-records-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.bk-records-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px;
}
</style>

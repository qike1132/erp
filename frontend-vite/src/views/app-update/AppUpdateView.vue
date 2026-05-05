<template>
  <div class="au-container">
    <div class="au-card au-card-main">
      <div class="au-card-header">
        <div class="au-card-title-group">
          <div class="au-icon-box au-icon-blue">
            <i class="fas fa-mobile-alt" />
          </div>
          <div>
            <h3>App版本管理</h3>
            <small>上传新版APK → 发布 → 推送升级通知到所有设备</small>
          </div>
        </div>
      </div>

      <div class="au-body">
        <!-- 左栏：上传新版本 -->
        <div class="au-col">
          <div class="au-col-title"><i class="fas fa-upload" /> 上传新版本</div>
          <div class="au-col-content">
            <div class="au-section">
              <div class="au-section-label">版本信息</div>
              <div class="au-form-row">
                <div class="au-form-field">
                  <label>版本号</label>
                  <input v-model="versionName" type="text" class="au-form-input" placeholder="如 1.1" />
                </div>
                <div class="au-form-field">
                  <label>整数版本号</label>
                  <input v-model.number="versionCode" type="number" class="au-form-input" placeholder="如 2" min="1" />
                </div>
              </div>
              <div class="au-form-field">
                <label>更新日志</label>
                <textarea v-model="changelog" class="au-form-textarea" rows="4" placeholder="本次更新内容..." />
              </div>
              <div class="au-form-field">
                <label class="au-checkbox-label">
                  <input v-model="forceUpdate" type="checkbox" />
                  <span>强制更新（用户无法跳过）</span>
                </label>
              </div>
            </div>

            <div class="au-section">
              <div class="au-section-label">APK文件</div>
              <div
                class="au-drop-zone"
                :class="{ 'au-drop-active': dragOver }"
                tabindex="0"
                role="button"
                aria-label="选择APK文件"
                @click="fileInputRef?.click()"
                @keydown.enter="fileInputRef?.click()"
                @keydown.space.prevent="fileInputRef?.click()"
                @dragover.prevent="dragOver = true"
                @dragleave="dragOver = false"
                @drop.prevent="handleDrop"
              >
                <div v-if="selectedFile" class="au-file-info">
                  <i class="fas fa-android" />
                  <span class="au-file-name">{{ selectedFile.name }}</span>
                  <span class="au-file-size">({{ formatSize(selectedFile.size) }})</span>
                  <button class="au-file-clear" @click.stop="clearFile"><i class="fas fa-times" /></button>
                </div>
                <div v-else class="au-drop-hint">
                  <i class="fas fa-cloud-upload-alt" />
                  <span>拖拽 .apk 文件到此处，或点击选择</span>
                </div>
              </div>
              <input ref="fileInputRef" type="file" accept=".apk" style="display: none" @change="onFileSelect" />
            </div>

            <button
              class="au-action-btn au-action-primary"
              :disabled="uploading || !canUpload"
              @click="handleUpload"
            >
              <i :class="uploading ? 'fas fa-spinner fa-spin' : 'fas fa-upload'" />
              {{ uploading ? '正在上传...' : '上传APK' }}
            </button>
          </div>
        </div>

        <!-- 右栏：版本列表 -->
        <div class="au-col">
          <div class="au-col-title"><i class="fas fa-list" /> 版本历史</div>
          <div class="au-col-content">
            <div v-if="versionsLoading" class="au-loading-inline"><i class="fas fa-spinner fa-spin" /> 加载中...</div>

            <div v-else-if="!versions.length" class="au-empty-state">
              <i class="fas fa-inbox" />
              <p>暂无版本记录</p>
              <small>上传第一个APK开始OTA升级</small>
            </div>

            <div v-else class="au-version-list">
              <div v-for="v in versions" :key="v.id" class="au-version-item" :class="{ 'au-version-published': v.is_active && v.pushed, 'au-version-pending': !v.is_active }">
                <div class="au-version-header">
                  <div class="au-version-name">
                    <i class="fas fa-code-branch" />
                    <span>v{{ v.version_name }}</span>
                    <span class="au-version-code">(#{{ v.version_code }})</span>
                    <span v-if="v.force_update" class="au-badge au-badge-danger">强制</span>
                    <span v-if="!v.is_active" class="au-badge au-badge-warning">待发布</span>
                    <span v-else-if="v.is_active && v.pushed" class="au-badge au-badge-success">已发布</span>
                    <span v-else-if="v.is_active && !v.pushed" class="au-badge au-badge-info">已激活</span>
                  </div>
                </div>
                <div class="au-version-meta">
                  <span><i class="fas fa-calendar" /> {{ v.created_at }}</span>
                  <span v-if="v.file_size"><i class="fas fa-weight" /> {{ formatSize(v.file_size) }}</span>
                  <span v-if="v.md5_hash"><i class="fas fa-fingerprint" /> {{ v.md5_hash?.substring(0, 8) }}...</span>
                </div>
                <div v-if="v.changelog" class="au-version-changelog">
                  <i class="fas fa-file-alt" /> {{ v.changelog }}
                </div>
                <div class="au-version-actions">
                  <button
                    v-if="!v.is_active || !v.pushed"
                    class="au-icon-btn au-icon-btn-publish"
                    :disabled="publishingId === v.id"
                    @click="handlePublish(v.id, v.version_name)"
                    title="发布版本并推送通知"
                  >
                    <i :class="publishingId === v.id ? 'fas fa-spinner fa-spin' : 'fas fa-rocket'" />
                    发布
                  </button>
                  <span v-else class="au-published-label"><i class="fas fa-check-circle" /> 已发布</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { upload, get, post } from '@/api/request'
import { showToast } from '@/composables/useToast'

interface AppVersion {
  id: number
  platform: string
  version_code: number
  version_name: string
  download_url: string
  changelog: string | null
  file_size: number | null
  md5_hash: string | null
  force_update: boolean
  is_active: boolean
  pushed: boolean
  created_at: string | null
}

const versionName = ref('')
const versionCode = ref<number>(1)
const changelog = ref('')
const forceUpdate = ref(false)
const selectedFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)
const uploading = ref(false)
const versions = ref<AppVersion[]>([])
const versionsLoading = ref(false)
const publishingId = ref<number | null>(null)

const canUpload = computed(() => versionName.value && versionCode.value > 0 && selectedFile.value)

function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.length) setFile(input.files[0])
}

function handleDrop(e: DragEvent) {
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) setFile(file)
}

function setFile(file: File) {
  if (!file.name.endsWith('.apk')) {
    showToast('请选择 .apk 文件', 'warning')
    return
  }
  selectedFile.value = file
}

function clearFile() {
  selectedFile.value = null
  if (fileInputRef.value) fileInputRef.value.value = ''
}

async function handleUpload() {
  if (!selectedFile.value || !versionName.value) return
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    formData.append('version_name', versionName.value)
    formData.append('version_code', String(versionCode.value))
    formData.append('changelog', changelog.value)
    formData.append('force_update', String(forceUpdate.value))
    await upload('/app/upload', formData)
    showToast('APK上传成功，状态：待发布', 'success')
    versionName.value = ''
    versionCode.value = 1
    changelog.value = ''
    forceUpdate.value = false
    clearFile()
    loadVersions()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '上传失败', 'error')
  } finally {
    uploading.value = false
  }
}

async function handlePublish(id: number, name: string) {
  publishingId.value = id
  try {
    await post(`/app/${id}/publish`)
    showToast(`v${name} 已发布，升级通知已推送到所有设备`, 'success')
    loadVersions()
  } catch (e: any) {
    showToast(e?.response?.data?.detail || '发布失败', 'error')
  } finally {
    publishingId.value = null
  }
}

async function loadVersions() {
  versionsLoading.value = true
  try {
    const res = await get<AppVersion[]>('/app/versions')
    versions.value = res
  } catch {
    showToast('加载版本列表失败', 'error')
  } finally {
    versionsLoading.value = false
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

loadVersions()
</script>

<style scoped>
.au-container { padding: 8px; margin: 0 auto; height: 100%; display: flex; flex-direction: column; box-sizing: border-box; }
.au-card { background: white; border-radius: 18px; border: 1px solid var(--color-border-light); box-shadow: var(--shadow-sm); transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1); }
.au-card:hover { box-shadow: var(--shadow-md); }
.au-card-main { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.au-card-header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; padding: 14px 24px 10px; flex-shrink: 0; gap: 12px; }
.au-card-title-group { display: flex; align-items: center; gap: 14px; }
.au-card-title-group h3 { font-size: 14px; font-weight: 700; color: var(--color-text); margin: 0; }
.au-card-title-group small { font-size: 12px; color: var(--color-text-secondary); display: block; margin-top: 2px; }
.au-icon-box { width: 46px; height: 46px; border-radius: 13px; display: flex; align-items: center; justify-content: center; font-size: 19px; flex-shrink: 0; }
.au-icon-blue { background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200)); color: var(--color-primary-700); }
.au-body { display: grid; grid-template-columns: 1fr 1fr; flex: 1; min-height: 0; overflow: hidden; }
.au-col { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.au-col + .au-col { border-left: 1px solid var(--color-border-light); }
.au-col-title { display: flex; align-items: center; gap: 8px; padding: 12px 20px; font-size: 14px; font-weight: 700; color: var(--color-text); border-bottom: 1px solid var(--color-border-light); flex-shrink: 0; }
.au-col-title i { font-size: 14px; color: var(--color-primary-500); }
.au-col-content { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 20px; }
.au-section { margin-bottom: 20px; }
.au-section-label { font-size: 12px; font-weight: 600; color: var(--color-text-secondary); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em; }
.au-form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.au-form-field { margin-bottom: 12px; }
.au-form-field label { display: block; font-size: 12px; font-weight: 600; color: var(--color-text-secondary); margin-bottom: 4px; }
.au-form-input { width: 100%; padding: 8px 12px; border: 2px solid var(--color-ocean-light); border-radius: var(--radius-input); font-size: 14px; outline: none; transition: all 0.3s ease; background: white; font-family: inherit; color: var(--color-text); box-sizing: border-box; min-height: 44px; }
.au-form-input:focus { border-color: var(--color-ocean-deep); box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1); }
.au-form-textarea { width: 100%; padding: 8px 12px; border: 2px solid var(--color-ocean-light); border-radius: var(--radius-input); font-size: 14px; outline: none; transition: all 0.3s ease; background: white; font-family: inherit; color: var(--color-text); box-sizing: border-box; resize: vertical; }
.au-form-textarea:focus { border-color: var(--color-ocean-deep); box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1); }
.au-checkbox-label { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--color-text); cursor: pointer; }
.au-checkbox-label input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--color-primary-500); }
.au-drop-zone { border: 2px dashed var(--color-ocean-light); border-radius: var(--radius-input); padding: 28px 20px; text-align: center; cursor: pointer; transition: all 0.3s ease; background: white; }
.au-drop-zone:hover, .au-drop-active { border-color: var(--color-ocean-deep); background: var(--color-ocean-light); }
.au-drop-hint { display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--color-text-muted); font-size: 14px; }
.au-drop-hint i { font-size: 28px; color: var(--color-primary-300); }
.au-file-info { display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--color-text); font-size: 14px; }
.au-file-info > i { color: var(--color-success-500); }
.au-file-name { font-weight: 600; }
.au-file-size { color: var(--color-text-secondary); font-size: 12px; }
.au-file-clear { background: none; border: none; color: var(--color-text-muted); cursor: pointer; padding: 4px; border-radius: 50%; transition: all 0.2s ease; }
.au-file-clear:hover { background: var(--color-danger-50); color: var(--color-danger-500); }
.au-action-btn { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; padding: 12px 18px; border: 2px solid var(--color-border-light); border-radius: var(--radius-button); background: white; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.3s ease; }
.au-action-primary { color: var(--color-primary-600); background: linear-gradient(135deg, var(--color-primary-50), white); border-color: var(--color-primary-200); }
.au-action-primary:hover:not(:disabled) { background: var(--color-primary-100); border-color: var(--color-primary-400); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
.au-action-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.au-version-list { display: flex; flex-direction: column; gap: 10px; }
.au-version-item { border: 1px solid var(--color-border-light); border-radius: var(--radius-sm); padding: 14px 16px; transition: all 0.3s ease; background: white; }
.au-version-item:hover { border-color: var(--color-primary-200); box-shadow: var(--shadow-sm); }
.au-version-published { border-left: 3px solid var(--color-success-500); }
.au-version-pending { border-left: 3px solid var(--color-warning-500, #f59e0b); background: linear-gradient(135deg, #fffbeb, white); }
.au-version-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.au-version-name { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 700; color: var(--color-text); }
.au-version-name i { color: var(--color-primary-500); }
.au-version-code { font-weight: 400; color: var(--color-text-secondary); font-size: 12px; }
.au-badge { display: inline-flex; align-items: center; font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 600; }
.au-badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }
.au-badge-success { background: var(--color-success-50); color: var(--color-success-600); }
.au-badge-info { background: var(--color-info-50); color: var(--color-info-600); }
.au-badge-warning { background: #fef3c7; color: #92400e; }
.au-version-meta { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: var(--color-text-secondary); }
.au-version-meta i { margin-right: 3px; font-size: 11px; color: var(--color-text-muted); }
.au-version-changelog { margin-top: 8px; padding: 6px 10px; background: var(--color-surface); border-radius: 6px; font-size: 12px; color: var(--color-text-secondary); }
.au-version-changelog i { margin-right: 4px; color: var(--color-primary-400); }
.au-version-actions { margin-top: 8px; display: flex; justify-content: flex-end; }
.au-icon-btn-publish { display: flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 8px; border: none; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600)); color: white; cursor: pointer; font-size: 13px; font-weight: 700; transition: all 0.2s ease; box-shadow: 0 2px 8px rgba(0, 148, 191, 0.3); }
.au-icon-btn-publish:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0, 148, 191, 0.4); }
.au-icon-btn-publish:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.au-published-label { font-size: 12px; color: var(--color-success-500); display: flex; align-items: center; gap: 4px; font-weight: 600; }
.au-empty-state { text-align: center; padding: 40px 20px; color: var(--color-text-muted); }
.au-empty-state i { font-size: 36px; color: var(--color-border-light); margin-bottom: 12px; display: block; }
.au-empty-state p { font-size: 14px; font-weight: 600; color: var(--color-text-secondary); margin: 0 0 4px; }
.au-empty-state small { font-size: 12px; }
.au-loading-inline { text-align: center; padding: 20px; color: var(--color-primary-500); font-size: 14px; }
</style>

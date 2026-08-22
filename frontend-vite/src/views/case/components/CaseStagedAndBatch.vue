<template>
  <div class="cs-right-col">
    <div class="cs-staged-section">
      <div class="cs-section-header">
        <div class="cs-section-title">
          <FontAwesomeIcon icon="layer-group" />
          {{ mode === 'stockin' ? '暂存入库列表' : '暂存出库列表' }}
        </div>
        <span class="cs-staged-count">共 {{ staged.length }} 个</span>
      </div>
      <div class="cs-staged-scroll">
        <div v-if="staged.length === 0" class="cs-staged-empty">
          <FontAwesomeIcon :icon="mode === 'stockin' ? 'box-open' : 'shipping-fast'" aria-hidden="true" />
          <p>{{ mode === 'stockin' ? '暂无暂存入库' : '暂无暂存出库' }}</p>
        </div>
        <div
          v-for="(item, idx) in staged"
          :key="item.id"
          :class="['cs-staged-item', mode === 'stockin' ? 'cs-staged-in' : 'cs-staged-out']"
        >
          <div class="cs-staged-info">
            <div class="cs-staged-product">
              <FontAwesomeIcon icon="cubes" :style="{ color: mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)', marginRight: '4px' }" />
              {{ item.productName }}
            </div>
            <div class="cs-staged-meta"><FontAwesomeIcon icon="user" style="margin-right: 4px" />{{ item.customer || '无客户' }}</div>
            <div class="cs-staged-badges">
              <span :class="['cs-badge-tag', mode === 'stockin' ? 'cs-tag-info' : 'cs-tag-danger']">数量: {{ item.quantity }}</span>
              <span class="cs-badge-tag cs-tag-secondary">{{ item.date }}</span>
            </div>
          </div>
          <button class="cs-icon-btn cs-icon-danger" aria-label="删除" @click="emit('remove-staged', idx)"><FontAwesomeIcon icon="trash" /></button>
        </div>
      </div>
    </div>

    <!-- 批量导入 -->
    <div class="cs-batch-section">
      <div class="cs-section-header cs-collapsible" @click="showBatchUpload = !showBatchUpload">
        <div class="cs-section-title">
          <FontAwesomeIcon :icon="mode === 'stockin' ? 'file-import' : 'file-export'" :style="{ color: mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)' }" aria-hidden="true" />
          {{ mode === 'stockin' ? '批量导入入库' : '批量导出出库' }}
        </div>
        <FontAwesomeIcon icon="chevron-down" :class="['cs-collapse-arrow', { expanded: showBatchUpload }]" />
      </div>
      <div v-if="showBatchUpload" class="cs-batch-content">
        <UiUpload accept=".xlsx,.xls" placeholder="拖拽 Excel 文件到这里，或点击选择文件（支持 .xlsx / .xls）" @change="emit('excel-change', $event)" />
        <div v-if="excelFile" class="cs-file-selected">
          <FontAwesomeIcon icon="file-excel" style="color: var(--color-success-500); margin-right: 6px" />{{ excelFile.name }}
        </div>
        <div class="cs-batch-actions">
          <button class="cs-action-btn cs-action-outline" :disabled="templateDownloading" aria-label="下载模板" @click="emit('download-template')">
            <UiLoadingIcon :loading="templateDownloading" icon="file-excel" />下载模板
          </button>
          <button :class="['cs-action-btn', mode === 'stockin' ? 'cs-action-primary' : 'cs-action-danger']" :disabled="!excelFile || importing" :aria-label="importing ? '导入中…' : '开始导入'" @click="emit('import-excel')">
            <UiLoadingIcon :loading="importing" icon="upload" style="margin-right: 4px" />{{ importing ? '导入中…' : '开始导入' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type {
  StagedStockItem,
} from '../composables/useCaseStockEntry'

defineProps<{
  mode: 'stockin' | 'stockout'
  staged: StagedStockItem[]
  excelFile: File | null
  importing: boolean
  templateDownloading: boolean
}>()

const emit = defineEmits<{
  'remove-staged': [idx: number]
  'excel-change': [files: FileList]
  'download-template': []
  'import-excel': []
}>()

const showBatchUpload = defineModel<boolean>('showBatchUpload', { default: false })
</script>

<style scoped>
.cs-right-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.cs-staged-section, .cs-batch-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}

.cs-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.cs-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.cs-section-title i {
  font-size: 14px;
}
.cs-collapsible {
  cursor: pointer;
}

/* Staged list */
.cs-staged-scroll {
  max-height: 350px;
  overflow-y: auto;
  padding: 12px 16px;
}
.cs-staged-empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: 32px 0;
}
.cs-staged-empty i { font-size: 28px; opacity: 0.3; display: block; margin-bottom: 8px; }
.cs-staged-count { color: var(--color-text-secondary); font-size: 13px; }
.cs-staged-item {
  border: 2px solid;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  transition: transform 0.3s ease;
}
.cs-staged-item:hover { transform: translateY(-1px); }
.cs-staged-in { border-color: var(--color-primary-200); }
.cs-staged-out { border-color: var(--color-danger-100); }
.cs-staged-info { flex: 1; }
.cs-staged-product { font-weight: 600; margin-bottom: 4px; font-size: 13px; }
.cs-staged-meta { color: var(--color-text-secondary); font-size: 12px; margin-bottom: 4px; }
.cs-staged-badges { display: flex; gap: 6px; }
.cs-badge-tag { padding: 2px 8px; border-radius: 99px; font-size: 11px; font-weight: 500; }
.cs-tag-info { background: var(--color-info-50); color: var(--color-info-700); }
.cs-tag-danger { background: var(--color-danger-50); color: var(--color-danger-700); }
.cs-tag-secondary { background: var(--color-border-light); color: var(--color-text-secondary); }

/* Icon buttons */
.cs-icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.2s ease;
}
.cs-icon-danger { background: var(--color-danger-50); color: var(--color-danger-500); }
.cs-icon-danger:hover { background: var(--color-danger-100); }

/* Action buttons */
.cs-action-btn {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
  color: var(--color-text-secondary);
}
.cs-action-primary { color: var(--color-primary-600); }
.cs-action-primary:hover:not(:disabled) { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.cs-action-danger { color: var(--color-danger-500); }
.cs-action-danger:hover:not(:disabled) { background: var(--color-danger-50); border-color: var(--color-danger-200); transform: translateY(-1px); }
.cs-action-outline { }
.cs-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Batch */
.cs-batch-content { padding: 12px 16px; }
.cs-file-selected { margin-top: 8px; font-size: 13px; color: var(--color-text-secondary); }
.cs-batch-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; }

/* Collapse arrow */
.cs-collapse-arrow { color: var(--color-text-muted); transition: transform 0.25s ease; }
.cs-collapse-arrow.expanded { transform: rotate(180deg); }
</style>
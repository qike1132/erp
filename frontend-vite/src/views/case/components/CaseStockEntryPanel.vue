<template>
  <!-- 上半部分：录入表单 + 暂存列表（自 CaseStockTab.vue 原样搬移） -->
  <div class="cs-top-row">
    <!-- 左：信息录入 -->
    <div class="cs-form-section">
      <div class="cs-section-header">
          <div class="cs-section-title">
            <FontAwesomeIcon :icon="mode === 'stockin' ? 'truck-loading' : 'shipping-fast'" :style="{ color: mode === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)' }" aria-hidden="true" />
            {{ mode === 'stockin' ? '入库信息录入' : '出库信息录入' }}
          </div>
          <span v-if="staged.length" :class="['cs-badge', mode === 'stockin' ? 'cs-badge-info' : 'cs-badge-danger']">
            已暂存: {{ staged.length }}
          </span>
        </div>

        <form @submit.prevent class="cs-form">
          <div class="cs-form-row">
            <div class="cs-form-field">
              <label class="cs-form-label">客户名称</label>
              <UiSelect v-model="form.customer" placeholder="请选择客户" :options="customerOptions" />
            </div>
            <div class="cs-form-field">
              <label class="cs-form-label">{{ mode === 'stockin' ? '入库时间' : '出库时间' }}</label>
              <UiDatePicker v-model="form.date" style="width: 100%" />
            </div>
          </div>

          <div class="cs-form-row" style="grid-template-columns: 2fr 1fr">
            <div class="cs-form-field">
              <label class="cs-form-label">产品名称</label>
              <UiAutocomplete
                v-model="form.search"
                :searchFn="searchFn"
                placeholder="输入产品名称或69码搜索"
                @select="onProductSelect"
              >
                <template #option="{ item }">
                  {{ item.name }}
                  <span v-if="item.barcode" class="cs-barcode-hint">{{ item.barcode }}</span>
                </template>
              </UiAutocomplete>
              <small v-if="mode === 'stockout' && form.productId" class="cs-current-stock">当前库存: {{ currentStock }}</small>
            </div>
            <div class="cs-form-field">
              <label class="cs-form-label">{{ mode === 'stockin' ? '入库数量' : '出库数量' }}</label>
              <input type="number" class="cs-input" v-model.number="form.quantity" min="1" step="1" />
            </div>
          </div>

          <div class="cs-form-field">
            <label class="cs-form-label">备注</label>
            <textarea v-model="form.note" class="cs-textarea" rows="2" :placeholder="mode === 'stockin' ? '例如：批量入库' : '例如：批量出库'" />
          </div>

          <button
            type="button"
            :class="['cs-submit-btn', canAdd ? (mode === 'stockin' ? 'cs-submit-primary' : 'cs-submit-danger') : 'cs-submit-disabled']"
            :disabled="!canAdd"
            @click="emit('add-staged')"
          >
            <FontAwesomeIcon icon="plus-circle" style="margin-right: 4px" />{{ mode === 'stockin' ? '新增入库' : '新增出库' }}
          </button>
        </form>
      </div>

      <!-- 右：暂存列表 + 批量导入 -->
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
              <button class="cs-icon-btn cs-icon-danger" @click="emit('remove-staged', idx)" aria-label="删除"><FontAwesomeIcon icon="trash" /></button>
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
              <button class="cs-action-btn cs-action-outline" :disabled="templateDownloading" @click="emit('download-template')">
                <UiLoadingIcon :loading="templateDownloading" icon="file-excel" />下载模板
              </button>
              <button :class="['cs-action-btn', mode === 'stockin' ? 'cs-action-primary' : 'cs-action-danger']" :disabled="!excelFile || importing" @click="emit('import-excel')">
                <i :loading="importing" icon="upload" style="margin-right: 4px" />{{ importing ? '导入中…' : '开始导入' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
</template>

<script setup lang="ts">
/**
 * CaseStockEntryPanel — 皮套入库/出库「信息录入 + 暂存列表 + 批量导入」面板
 * 模板与样式自 CaseStockTab.vue 原样搬移，仅将原组件内变量改为 props/emits 绑定。
 */
import type {
  CaseProductOption,
  CaseStockFormState,
  CustomerOption,
  StagedStockItem,
} from '../composables/useCaseStockEntry'

defineProps<{
  /** 当前模式：入库 / 出库 */
  mode: 'stockin' | 'stockout'
  /** 录入表单（reactive 对象，属性由本组件直接 v-model 修改） */
  form: CaseStockFormState
  /** 暂存列表 */
  staged: StagedStockItem[]
  /** 出库模式下的当前库存 */
  currentStock: number
  /** 客户下拉选项 */
  customerOptions: CustomerOption[]
  /** 是否允许加入暂存列表 */
  canAdd: boolean
  /** 产品远程搜索函数 */
  searchFn: (query: string) => Promise<CaseProductOption[]>
  /** 已选择的 Excel 文件 */
  excelFile: File | null
  /** 是否导入中 */
  importing: boolean
  /** 是否模板下载中 */
  templateDownloading: boolean
}>()

/** 批量导入面板折叠状态（v-model:show-batch-upload） */
const showBatchUpload = defineModel<boolean>('showBatchUpload', { default: false })

const emit = defineEmits<{
  /** 选中产品搜索候选项 */
  'product-select': [product: CaseProductOption]
  /** 新增暂存 */
  'add-staged': []
  /** 删除暂存项 */
  'remove-staged': [idx: number]
  /** Excel 文件选择变化 */
  'excel-change': [files: FileList]
  /** 下载导入模板 */
  'download-template': []
  /** 开始导入 */
  'import-excel': []
}>()

/** 产品选中：转发给父组件（原模板内联调用 onProductSelect，改为 emits 绑定） */
function onProductSelect(product: CaseProductOption) {
  emit('product-select', product)
}
</script>

<style scoped>
/* Top row */
.cs-top-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 992px) {
  .cs-top-row { grid-template-columns: 1fr; }
}
.cs-form-section, .cs-staged-section, .cs-batch-section, .cs-record-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.cs-right-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Section headers */
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

/* Form */
.cs-form {
  padding: 16px;
}
.cs-form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.cs-form-field {
  margin-bottom: 12px;
}
.cs-form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.cs-input {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}
.cs-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cs-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cs-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  color: var(--color-text);
  resize: vertical;
  font-family: inherit;
  background: white;
  outline: none;
  transition: border-color 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
}
.cs-textarea:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.cs-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.cs-current-stock {
  display: block;
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

/* Submit buttons */
.cs-submit-btn {
  width: 100%;
  padding: 9px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cs-submit-primary { background: var(--color-primary-50); color: var(--color-primary-600); border: 2px solid var(--color-primary-300); }
.cs-submit-primary:hover { background: var(--color-primary-100); transform: translateY(-1px); }
.cs-submit-danger { background: var(--color-danger-50); color: var(--color-danger-600); border: 2px solid var(--color-danger-300); }
.cs-submit-danger:hover { background: var(--color-danger-100); transform: translateY(-1px); }
.cs-submit-disabled { background: var(--color-surface, #f8fafc); color: var(--color-text-muted); border: 2px solid var(--color-border-light); cursor: not-allowed; opacity: 0.4; }

/* Badges */
.cs-badge {
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.cs-badge-info { background: var(--color-primary-50); color: var(--color-primary-600); }
.cs-badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }

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

.cs-barcode-hint { color: var(--color-text-muted); font-size: 11px; }
</style>

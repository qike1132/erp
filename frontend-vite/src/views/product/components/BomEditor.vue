<template>
  <Teleport to="body">
    <div v-if="bomDialogVisible" class="pd-overlay" @click.self="bomDialogVisible = false">
      <div class="bom-modal-content bom-modal-dialog">
        <div class="bom-modal-header">
          <div class="bom-modal-header-left">
            <h5 class="bom-modal-title"><FontAwesomeIcon icon="cogs" aria-hidden="true" /><span>BOM表配置 - {{ bomProductName }}</span></h5>
          </div>
          <button class="bom-modal-close" @click="bomDialogVisible = false" aria-label="关闭"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
        </div>
        <div class="bom-modal-body">
          <div class="bom-tabs-container">
            <button v-for="tab in bomTabs" :key="tab.key" class="bom-tab-v2" :class="{ active: currentBomCategory === tab.key }" @click="switchBomTab(tab.key)" :aria-label="tab.label">
              <i :class="tab.icon" aria-hidden="true"></i> {{ tab.label }}
            </button>
          </div>
          <div class="bom-main-content">
            <div class="bom-summary-bar">
              <div class="bom-summary-left">
                <span class="bom-summary-text"><FontAwesomeIcon icon="list" aria-hidden="true" />{{ currentBomTabLabel }}物料清单</span>
                <span class="bom-summary-count">物料总数：<span class="count-value">{{ currentBomItems.length }}</span></span>
              </div>
              <div class="bom-summary-center">
                <div class="pd-input-wrap autocomplete-wrapper">
                  <UiAutocomplete
                    v-model="quickCopyKeyword"
                    :searchFn="searchProductsForBom"
                    placeholder="输入产品名称或条码，直接复制BOM"
                    @select="selectAutocompleteItem"
                  >
                    <template #option="{ item }">
                      <div class="flex items-center justify-between w-full gap-2">
                        <div class="flex-1 min-w-0">
                          <div class="product-name">{{ item.name }}</div>
                          <div class="product-info text-xs text-text-muted">{{ item.barcode ? '条码: ' + item.barcode : '' }}</div>
                        </div>
                        <span class="product-status text-xs" :class="item.has_bom ? 'has-bom' : 'no-bom'">
                          {{ item.has_bom ? '有BOM' : '无BOM' }}
                        </span>
                      </div>
                    </template>
                  </UiAutocomplete>
                </div>
              </div>
              <div class="bom-summary-right">
                <button class="bom-btn-copy-v2" :disabled="quickCopyLoading" @click="quickCopyBom"><FontAwesomeIcon icon="copy" aria-hidden="true" />复制BOM</button>
                <button class="bom-btn-add-v2" @click="addBomItem"><FontAwesomeIcon icon="plus" aria-hidden="true" />添加物料</button>
              </div>
            </div>
            <div v-if="quickCopyProgress.visible" class="mb-3">
              <div class="pd-progress"><div class="pd-progress-bar" :style="{ width: quickCopyProgress.percent + '%' }"></div></div>
              <p class="pd-progress-text">{{ quickCopyProgress.text }}</p>
            </div>
            <div class="bom-content-area">
              <div v-if="currentBomItems.length > 0" class="bom-table-container-v2">
                <div class="bom-table-wrapper-v2">
                  <table class="bom-table-v2">
                    <thead class="bom-table-header-v2">
                      <tr>
                        <th style="width:200px">物料名称 <span class="required">*</span></th>
                        <th style="width:180px">规格型号 <span class="required">*</span></th>
                        <th style="width:120px">计量单位 <span class="required">*</span></th>
                        <th style="width:200px">默认供应商 <span class="required">*</span></th>
                        <th style="width:140px">单SKU用量</th>
                        <th style="width:200px">备注</th>
                        <th style="width:80px">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(item, idx) in currentBomItems" :key="item.id ?? 'bom-' + idx">
                        <td><input v-model="item.name" type="text" class="bom-table-input" placeholder="输入物料名称" name="material-name" autocomplete="off" /></td>
                        <td><input v-model="item.specification" type="text" class="bom-table-input" placeholder="输入规格型号" name="specification" autocomplete="off" /></td>
                        <td>
                          <select v-model="item.unit" class="bom-table-select">
                            <option value="码">码</option><option value="克">克</option><option value="个">个</option>
                            <option value="件">件</option><option value="套">套</option><option value="米">米</option><option value="平方">平方</option>
                          </select>
                        </td>
                        <td><input v-model="item.supplier_name" type="text" class="bom-table-input" placeholder="输入供应商名称" name="supplier-name" autocomplete="off" /></td>
                        <td><input v-model.number="item.usage" type="number" class="bom-table-input" step="0.01" min="0" name="quantity" autocomplete="off" /></td>
                        <td><input v-model="item.remark" type="text" class="bom-table-input" placeholder="输入备注" name="remark" autocomplete="off" /></td>
                        <td><button class="bom-table-action-btn delete" @click="deleteBomItem(idx)" aria-label="删除"><FontAwesomeIcon icon="trash" aria-hidden="true" /></button></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div v-else class="bom-empty-state-v2">
                <div class="bom-empty-icon"><FontAwesomeIcon icon="inbox" aria-hidden="true" /></div>
                <div class="bom-empty-text">
                  <p class="bom-empty-title">暂无物料</p>
                  <p class="bom-empty-hint">点击"添加物料"按钮开始配置</p>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="bom-modal-footer">
          <button class="bom-btn-cancel" @click="bomDialogVisible = false">取消</button>
          <button class="bom-btn-save" @click="saveBom"><FontAwesomeIcon icon="save" aria-hidden="true" />保存BOM</button>
        </div>
      </div>
    </div>
  </Teleport>

  <BomCopyDialog
    v-model:open="copyBomDialogVisible"
    v-model:search-keyword="copyBomSearchKeyword"
    v-model:overwrite="copyBomOverwrite"
    :products="copyBomProducts"
    :source-product-id="copyBomSourceProductId"
    :preview="copyBomPreview"
    :progress="copyBomProgress"
    @search="searchProductForCopy"
    @select-product="selectCopyBomProduct"
    @confirm="confirmCopyBom"
  />

  <UiConfirmDialog
    :open="confirmDialog.open"
    :text="confirmDialog.text"
    :sub="confirmDialog.sub"
    :type="confirmDialog.type"
    @confirm="confirmDialog.onConfirm"
    @cancel="confirmDialog.onCancel"
  />
</template>

<script setup lang="ts">
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useProductListActions } from '../composables/useProductListActions'
import BomCopyDialog from './BomCopyDialog.vue'

const confirmDialog = useConfirmDialog()

const {
  bomDialogVisible, bomProductName, currentBomCategory,
  bomTabs, currentBomItems, currentBomTabLabel,
  switchBomTab, openBomModal, addBomItem, deleteBomItem, saveBom,
  quickCopyKeyword, quickCopyLoading,
  quickCopyProgress,
  searchProductsForBom, selectAutocompleteItem, quickCopyBom,
  copyBomDialogVisible, copyBomSearchKeyword, copyBomProducts,
  copyBomSourceProductId, copyBomPreview, copyBomOverwrite, copyBomProgress,
  searchProductForCopy, selectCopyBomProduct, confirmCopyBom,
} = useProductListActions(confirmDialog)

defineExpose({ open: openBomModal })
</script>

<style scoped>
/* ===== 模态框遮罩 ===== */
.pd-overlay {
  position: fixed; inset: 0; z-index: 1050; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; padding: 16px;
}

.pd-input-wrap { position: relative; }
.autocomplete-wrapper { position: relative; }

/* ===== BOM模态框 ===== */
.bom-modal-content {
  border-radius: 18px; border: none; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  overflow: hidden; background: white;
}
.bom-modal-dialog { max-width: 1400px; width: 95vw; max-height: 90vh; display: flex; flex-direction: column; }
.bom-modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 28px; background: transparent;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.bom-modal-header-left { flex: 1; }
.bom-modal-title {
  display: flex; align-items: center; gap: 10px;
  font-size: 16px; font-weight: 700; color: var(--color-text); margin: 0;
}
.bom-modal-title i { color: var(--color-primary-500); }
.bom-modal-close {
  width: 36px; height: 36px; border: none; background: var(--color-surface, #f8fafc);
  border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: var(--color-text-secondary); font-size: 16px; transition: background 0.3s ease, color 0.3s ease, transform 0.3s ease;
}
.bom-modal-close:hover { background: var(--color-border-light, #e2e8f0); color: var(--color-text); transform: rotate(90deg); }
.bom-modal-body { padding: 0; background: var(--color-surface, #f8fafc); min-height: 500px; overflow-y: auto; flex: 1; }
.bom-tabs-container {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.bom-tab-v2 {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  display: flex;
  align-items: center;
  gap: 6px;
}
.bom-tab-v2:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.bom-tab-v2.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
.bom-main-content { padding: 20px 28px 28px; }
.bom-summary-bar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px; background: white; border-radius: 12px;
  border: 1px solid var(--color-primary-200); margin-bottom: 20px; gap: 12px; flex-wrap: wrap;
}
.bom-summary-left { display: flex; align-items: center; gap: 20px; }
.bom-summary-text { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; color: var(--color-text); }
.bom-summary-text i { color: var(--color-primary-500); }
.bom-summary-count { font-size: 13px; color: var(--color-text-secondary); }
.count-value { font-size: 18px; font-weight: 700; color: var(--color-primary-600); }
.bom-summary-center { flex: 1; max-width: 360px; margin: 0 16px; position: relative; }
.bom-summary-right { display: flex; gap: 8px; }
.bom-btn-add-v2 {
  padding: 10px 20px; background: var(--color-success-50); color: var(--color-success-600);
  border: 2px solid var(--color-success-200); border-radius: 10px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: transform 0.3s ease, box-shadow 0.3s ease; display: flex; align-items: center; gap: 6px;
}
.bom-btn-add-v2:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(34,197,94,0.2); }
.bom-btn-copy-v2 {
  padding: 10px 20px; background: var(--color-primary-50); color: var(--color-primary-600);
  border: 2px solid var(--color-primary-200); border-radius: 10px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: transform 0.3s ease, box-shadow 0.3s ease; display: flex; align-items: center; gap: 6px;
}
.bom-btn-copy-v2:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.2); }
.bom-btn-copy-v2:disabled { opacity: 0.4; cursor: not-allowed; transform: none; box-shadow: none; }

/* BOM内容区 */
.bom-content-area { background: white; border-radius: 12px; border: 1px solid var(--color-border-light, #e2e8f0); overflow: hidden; }
.bom-table-container-v2 { display: block; }
.bom-table-wrapper-v2 { overflow-x: auto; }
.bom-table-v2 { width: 100%; border-collapse: collapse; min-width: 1100px; }
.bom-table-header-v2 { background: var(--color-surface, #f8fafc); }
.bom-table-header-v2 th {
  padding: 12px 16px; text-align: left; font-size: 12px; font-weight: 600;
  color: var(--color-text); border-bottom: 2px solid var(--color-primary-200); white-space: nowrap;
}
.bom-table-header-v2 th .required { color: var(--color-danger-500); font-weight: 700; }
.bom-table-v2 tbody tr { transition: background-color 0.2s ease; }
.bom-table-v2 tbody tr:hover { background-color: var(--color-primary-50); }
.bom-table-v2 tbody td { padding: 10px 16px; border-bottom: 1px solid var(--color-border-light, #f1f5f9); vertical-align: middle; }
.bom-table-input {
  width: 100%; padding: 6px 10px; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px; font-size: 13px; transition: border-color 0.2s ease, box-shadow 0.2s ease; outline: none;
}
.bom-table-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1); }
.bom-table-select {
  width: 100%; padding: 6px 10px; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px; font-size: 13px; background: white; cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease; outline: none;
}
.bom-table-select:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1); }
.bom-table-action-btn { padding: 5px 8px; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; transition: transform 0.2s ease, box-shadow 0.2s ease; }
.bom-table-action-btn.delete { background: var(--color-danger-50); color: var(--color-danger-600); }
.bom-table-action-btn.delete:hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(229,115,115,0.3); }
.bom-empty-state-v2 { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px 20px; text-align: center; }
.bom-empty-icon { margin-bottom: 16px; }
.bom-empty-icon i { font-size: 48px; color: var(--color-text-secondary); opacity: 0.4; }
.bom-empty-text { display: flex; flex-direction: column; gap: 6px; }
.bom-empty-title { font-size: 16px; font-weight: 600; color: var(--color-text); margin: 0; }
.bom-empty-hint { font-size: 13px; color: var(--color-text-secondary); margin: 0; }

/* BOM底部按钮 */
.bom-modal-footer {
  display: flex; justify-content: flex-end; align-items: center; gap: 10px;
  padding: 20px 28px; background: white;
  border-top: 1px solid var(--color-border-light, #e2e8f0);
}
.bom-btn-cancel {
  padding: 10px 20px; background: white; color: var(--color-text);
  border: 2px solid var(--color-border-light, #e2e8f0); border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.3s ease, transform 0.3s ease;
}
.bom-btn-cancel:hover { background: var(--color-surface, #f8fafc); transform: translateY(-1px); }
.bom-btn-save {
  padding: 10px 20px; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  color: white; border: 2px solid var(--color-primary-500); border-radius: 10px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: transform 0.3s ease, box-shadow 0.3s ease;
  display: flex; align-items: center; gap: 6px;
}
.bom-btn-save:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59,130,246,0.3); }
.bom-btn-save:disabled { opacity: 0.4; cursor: not-allowed; }

/* 进度条 */
.pd-progress { height: 16px; border-radius: 8px; background: var(--color-border-light, #e2e8f0); overflow: hidden; }
.pd-progress-bar { height: 100%; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600)); border-radius: 8px; transition: width 0.3s ease; }
.pd-progress-text { margin-top: 6px; font-size: 12px; color: var(--color-text-secondary); text-align: center; }
</style>

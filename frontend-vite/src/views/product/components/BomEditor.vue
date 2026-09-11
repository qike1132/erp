<template>
  <Teleport to="body">
    <!-- 遮罩层刻意不绑定点击关闭：BOM 配置是长表单，误触弹窗外空白会导致未保存的配置全部丢失。
         关闭入口仅限：① 弹窗右上角关闭按钮 ② 底部「取消」按钮 ③ 保存成功后的自动关闭。
         请勿为「点遮罩即关」重新加回 @click.self，如需放弃编辑请走显式按钮。 -->
    <div v-if="bomDialogVisible" class="pd-overlay">
      <div class="bom-modal-content bom-modal-dialog">
        <div class="bom-modal-header">
          <div class="bom-modal-header-left">
            <h5 class="bom-modal-title"><FontAwesomeIcon icon="cogs" aria-hidden="true" /><span>BOM表配置 - {{ bomProductName }}</span></h5>
          </div>
          <button class="bom-modal-close" aria-label="关闭" @click="bomDialogVisible = false"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
        </div>
        <div class="bom-modal-body">
          <div class="bom-tabs-container">
            <button v-for="tab in bomTabs" :key="tab.key" class="bom-tab-v2" :class="{ active: currentBomCategory === tab.key }" :aria-label="tab.label" @click="switchBomTab(tab.key)">
              <FontAwesomeIcon :icon="tab.icon" aria-hidden="true" /> {{ tab.label }}
            </button>
          </div>
          <div class="bom-main-content">
            <div class="bom-summary-bar">
              <div class="bom-summary-left">
                <span class="bom-summary-text"><FontAwesomeIcon icon="list" aria-hidden="true" />{{ currentBomTabLabel }} · {{ currentScopeLabel }}</span>
                <span class="bom-summary-count">物料总数：<span class="count-value">{{ currentScopeCount }}</span></span>
              </div>
              <div class="bom-summary-center">
                <div class="pd-input-wrap autocomplete-wrapper">
                  <UiAutocomplete
                    v-model="quickCopyKeyword"
                    :search-fn="searchProductsForBom"
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
            <!-- 角色栏：物料表格上方，点击角色标签切换到对应角色的 BOM -->
            <div class="bom-role-bar">
              <span class="bom-role-label"><FontAwesomeIcon icon="user" aria-hidden="true" /> 角色：</span>
              <div v-if="bomRoles.length" class="bom-role-chips">
                <span
                  v-if="defaultScopeHasItems"
                  class="bom-role-chip"
                  :class="{ active: selectedRole === null }"
                  title="产品级默认BOM（无角色归属的存量物料）"
                  @click="selectRole(null)"
                >
                  默认BOM
                </span>
                <span
                  v-for="role in bomRoles"
                  :key="role.id ?? role.role_key"
                  class="bom-role-chip"
                  :class="{ active: selectedRole === role }"
                  :title="'点击切换BOM，双击重命名'"
                  @click="selectRole(role)"
                  @dblclick="startRename(role)"
                >
                  <input
                    v-if="renamingRole === role"
                    v-model="renameInput"
                    class="bom-role-rename-input"
                    maxlength="100"
                    @keydown.enter="commitRename"
                    @keydown.esc="cancelRename"
                    @blur="commitRename"
                    @click.stop
                  />
                  <template v-else>{{ role.name }}</template>
                  <button class="bom-role-rm" title="删除角色" @click.stop="removeRole(role)"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
                </span>
              </div>
              <span v-else class="bom-role-empty">尚未配置角色（当前为产品级默认BOM），点击"＋ 添加角色"开始</span>
              <span v-if="addingRole" class="bom-role-add-wrap">
                <input
                  ref="roleAddInputRef"
                  v-model="newRoleName"
                  class="bom-role-add-input"
                  maxlength="100"
                  placeholder="输入角色名称，回车确认"
                  @keydown.enter="commitAddRole"
                  @keydown.esc="cancelAddRole"
                  @blur="commitAddRole"
                />
              </span>
              <button v-else class="bom-role-add-btn" @click="startAddRole"><FontAwesomeIcon icon="plus" aria-hidden="true" />添加角色</button>
            </div>
            <div v-if="quickCopyProgress.visible" class="mb-3">
              <div class="pd-progress"><div class="pd-progress-bar" :style="{ width: quickCopyProgress.percent + '%' }" /></div>
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
                        <th style="width:200px">供应商 <span class="required">*</span></th>
                        <th style="width:140px">单个用量</th>
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
                        <td><button class="bom-table-action-btn delete" aria-label="删除" @click="deleteBomItem(idx)"><FontAwesomeIcon icon="trash" aria-hidden="true" /></button></td>
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
import { nextTick, ref } from 'vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useProductListActions } from '../composables/useProductListActions'
import type { Role } from '../composables/bomTypes'
import BomCopyDialog from './BomCopyDialog.vue'

const confirmDialog = useConfirmDialog()

const {
  bomDialogVisible, bomProductName, currentBomCategory,
  bomTabs, currentBomItems, currentBomTabLabel, currentScopeLabel, currentScopeCount,
  switchBomTab, openBomModal, addBomItem, deleteBomItem, saveBom,
  bomRoles, selectedRole, defaultScopeHasItems, selectRole, addRole, renameRole, removeRole,
  quickCopyKeyword, quickCopyLoading,
  quickCopyProgress,
  searchProductsForBom, selectAutocompleteItem, quickCopyBom,
  copyBomDialogVisible, copyBomSearchKeyword, copyBomProducts,
  copyBomSourceProductId, copyBomPreview, copyBomOverwrite, copyBomProgress,
  searchProductForCopy, selectCopyBomProduct, confirmCopyBom,
} = useProductListActions(confirmDialog)

// ===== 角色重命名（双击标签进入内联编辑） =====
const renamingRole = ref<Role | null>(null)
const renameInput = ref('')

function startRename(role: Role) {
  renamingRole.value = role
  renameInput.value = role.name
}
function commitRename() {
  if (renamingRole.value) renameRole(renamingRole.value, renameInput.value)
  renamingRole.value = null
}
function cancelRename() {
  renamingRole.value = null
}

// ===== 添加角色（内联输入，回车确认） =====
const addingRole = ref(false)
const newRoleName = ref('')
const roleAddInputRef = ref<HTMLInputElement | null>(null)

function startAddRole() {
  addingRole.value = true
  newRoleName.value = ''
  nextTick(() => roleAddInputRef.value?.focus())
}
function commitAddRole() {
  if (!addingRole.value) return
  addRole(newRoleName.value)
  addingRole.value = false
}
function cancelAddRole() {
  addingRole.value = false
}

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

/* ===== BOM模态框 =====
   尺寸契约（勿改回 height:auto）：弹窗**恒定高度**，不随物料条数变化。
   历史问题：max-height:90vh + 默认 height:auto + body 仅 min-height:500px，
   导致物料 1 条时弹窗 ~663px、20 条时 ~810px，视觉上「一会大一会小」。
   现在：dialog 固定 height:90vh（带 min/max 兜底），body 内部滚动，
   物料多少只影响 body 的滚动位置，弹窗外框尺寸始终一致。 */
.bom-modal-content {
  border-radius: 18px; border: none; box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  overflow: hidden; background: white;
}
.bom-modal-dialog {
  max-width: 1400px; width: 95vw;
  /* 固定高度：三种写法叠加，避免 90vh 在小屏/大屏下越界后又被内容撑开 */
  height: 90vh; min-height: 680px; max-height: 90vh;
  display: flex; flex-direction: column;
}
.bom-modal-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 28px; background: transparent;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  flex: 0 0 auto;
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
/* body：占满 dialog 剩余高度并内部滚动；min-height 取消（改为 flex:1 + min-height:0，
   否则内容少时 min-height 会反向撑高外框，又变成"尺寸随内容变"） */
.bom-modal-body {
  padding: 0; background: var(--color-surface, #f8fafc);
  flex: 1 1 auto; min-height: 0; overflow-y: auto;
}
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

/* ===== 角色栏（物料表格上方，点击角色切换 BOM） ===== */
.bom-role-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: white; border: 1px solid var(--color-primary-200); border-radius: 12px;
  padding: 10px 16px; margin-bottom: 12px;
}
.bom-role-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 14px; font-weight: 700; color: var(--color-text); white-space: nowrap;
}
.bom-role-label i { color: var(--color-primary-500); }
.bom-role-chips { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex: 1; }
.bom-role-chip {
  display: inline-flex; align-items: center; gap: 6px;
  border: 2px solid var(--color-primary-200); background: white; color: var(--color-primary-600);
  border-radius: 999px; padding: 4px 8px 4px 14px; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: background 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
  user-select: none;
}
.bom-role-chip:hover { background: var(--color-primary-50); transform: translateY(-1px); }
.bom-role-chip.active {
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-600));
  border-color: var(--color-primary-500); color: white;
  box-shadow: 0 4px 12px rgba(59,130,246,0.3);
}
.bom-role-rm {
  width: 18px; height: 18px; border: none; border-radius: 50%; cursor: pointer;
  background: transparent; color: inherit; opacity: 0.75; font-size: 12px;
  display: flex; align-items: center; justify-content: center; transition: background 0.2s ease, opacity 0.2s ease;
}
.bom-role-rm:hover { background: var(--color-danger-100); color: var(--color-danger-600); opacity: 1; }
.bom-role-rename-input {
  width: 110px; padding: 2px 8px; border: 1px solid var(--color-primary-400); border-radius: 8px;
  font-size: 13px; outline: none; box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1);
}
.bom-role-empty { font-size: 13px; color: var(--color-text-secondary); }
.bom-role-add-wrap { display: inline-flex; }
.bom-role-add-input {
  border: 1px solid var(--color-primary-400); border-radius: 999px; padding: 5px 14px;
  font-size: 13px; width: 180px; outline: none; box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1);
}
.bom-role-add-btn {
  display: inline-flex; align-items: center; gap: 6px;
  border: 2px dashed var(--color-primary-200); background: var(--color-primary-50);
  color: var(--color-primary-600); border-radius: 999px; padding: 5px 14px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s ease;
}
.bom-role-add-btn:hover { border-color: var(--color-primary-400); background: var(--color-primary-100); }

/* BOM内容区：给一个稳定的最小高度，保证「0 条(空态) / 1 条 / 多条」时
   内容区下沿位置一致，不会因为只有 1 行而显得弹窗塌陷 */
.bom-content-area {
  background: white; border-radius: 12px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  overflow: hidden;
  min-height: 300px;
}
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
  flex: 0 0 auto;
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
.pd-progress-bar { height: 100%; background: linear-gradient(135deg, var(--color-warning-400), var(--color-warning-600)); border-radius: 8px; transition: width 0.3s ease; }
.pd-progress-text { margin-top: 6px; font-size: 12px; color: var(--color-text-secondary); text-align: center; }
</style>

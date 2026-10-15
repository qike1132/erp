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
            <!-- 角色页签：左键切换 BOM 作用域，右键打开菜单（重命名 / 删除角色）
                 与 pattern-room RoleTabs 同形态（页签上不再放「⋯」按钮） -->
            <div class="bom-role-bar">
              <span class="bom-role-label"><FontAwesomeIcon icon="tags" aria-hidden="true" /> 角色：</span>
              <div class="bom-role-tabs">
                <!-- 默认BOM 页签（产品级，可重命名、不可删除） -->
                <div
                  v-if="defaultScopeHasItems"
                  class="bom-role-tab"
                  :class="{ active: selectedRole === null }"
                  tabindex="0"
                  title="右键打开菜单"
                  aria-haspopup="menu"
                  :aria-expanded="roleMenu?.key === 'default'"
                  @click="selectRole(null); closeMenu()"
                  @contextmenu="onRoleContextMenu($event, 'default')"
                  @keydown="onRoleTabKeydown($event, 'default')"
                >
                  <template v-if="renamingTarget === 'default'">
                    <input ref="renameInputRef" v-model="renameInput" class="bom-role-edit-input" maxlength="100"
                           @keydown.enter="commitRename" @keydown.esc="cancelRename" @blur="commitRename" @click.stop
                    />
                  </template>
                  <template v-else>
                    <span class="bom-role-name">{{ defaultScopeName }}</span>
                  </template>
                </div>
                <!-- 角色页签 -->
                <div
                  v-for="role in bomRoles"
                  :key="role.id ?? role.role_key"
                  class="bom-role-tab"
                  :class="{ active: selectedRole === role }"
                  tabindex="0"
                  title="右键打开菜单"
                  aria-haspopup="menu"
                  :aria-expanded="roleMenu?.key === role"
                  @click="selectRole(role); closeMenu()"
                  @contextmenu="onRoleContextMenu($event, role)"
                  @keydown="onRoleTabKeydown($event, role)"
                >
                  <template v-if="renamingTarget === role">
                    <input ref="renameInputRef" v-model="renameInput" class="bom-role-edit-input" maxlength="100"
                           @keydown.enter="commitRename" @keydown.esc="cancelRename" @blur="commitRename" @click.stop
                    />
                  </template>
                  <template v-else>
                    <span class="bom-role-name">{{ role.name }}</span>
                  </template>
                </div>
                <!-- 添加角色：与 pattern-room RoleTabs 的「新增角色」同形态
                     （常驻虚线图标按钮 → 右侧追加内联输入框；回车/失焦确认，Esc 取消） -->
                <span class="bom-role-add-wrap">
                  <button type="button" class="bom-role-add-btn" title="新增角色" aria-label="新增角色" @click="startAddRole"><FontAwesomeIcon icon="plus" aria-hidden="true" /></button>
                  <input
                    v-if="addingRole"
                    ref="roleAddInputRef"
                    v-model="newRoleName"
                    class="bom-role-add-input"
                    maxlength="100"
                    placeholder="角色名称"
                    @keydown.enter="commitAddRole"
                    @keydown.esc="cancelAddRole"
                    @blur="commitAddRole"
                  />
                </span>
              </div>
              <!-- P1-04：顶部常驻当前作用域徽标，避免误在别的角色作用域下编辑 -->
              <span class="bom-scope-badge" title="当前编辑作用域">
                <FontAwesomeIcon icon="tags" aria-hidden="true" />
                当前作用域：<strong>{{ currentScopeLabel }}</strong>
              </span>
              <span v-if="!bomRoles.length && !defaultScopeHasItems" class="bom-role-empty">尚未配置角色，点击「＋」新增角色开始</span>
              <!-- 右键菜单：与 pattern-room RoleTabs 的 .role-tab-menu 同形态
                   （遮罩负责点击/滚轮/再次右键关闭；键盘路径打开后焦点入首个菜单项）
                   必须留在角色栏**末尾**：v-if 节点插在兄弟列表中间时按位置配对会错位，
                   整栏（含页签）会被重建 → 焦点无法归还、内联改名输入被冲掉 -->
              <div
                v-if="roleMenu"
                class="bom-role-menu-mask"
                @click="closeMenu()"
                @contextmenu.prevent="closeMenu()"
                @wheel="closeMenu()"
              />
              <div v-if="roleMenu" class="bom-role-menu" role="menu" :style="{ left: `${roleMenu.x}px`, top: `${roleMenu.y}px` }">
                <button ref="menuItemEl" type="button" role="menuitem" class="bom-menu-item" @click="onMenuRename">
                  <FontAwesomeIcon icon="pencil-alt" aria-hidden="true" />
                  重命名
                </button>
                <template v-if="roleMenu.key !== 'default'">
                  <div class="bom-menu-divider" />
                  <button type="button" role="menuitem" class="bom-menu-item danger" @click="onMenuRemove">
                    <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
                    删除角色
                  </button>
                </template>
              </div>
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
                        <td>
                          <BomSupplierSelect v-model="item.supplier_name" :options="bomSupplierOptions" />
                        </td>
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
    overlay-z-class="z-[var(--z-overlay-nested)]"
    content-z-class="z-[var(--z-modal-nested)]"
    @confirm="confirmDialog.onConfirm"
    @cancel="confirmDialog.onCancel"
  />
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useProductListActions } from '../composables/useProductListActions'
import type { Role } from '../composables/bomTypes'
import BomCopyDialog from './BomCopyDialog.vue'
import BomSupplierSelect from './BomSupplierSelect.vue'

const confirmDialog = useConfirmDialog()

const {
  bomDialogVisible, bomProductName, currentBomCategory,
  bomTabs, currentBomItems, currentBomTabLabel, currentScopeLabel, currentScopeCount,
  switchBomTab, openBomModal, addBomItem, deleteBomItem, saveBom,
  bomSupplierOptions,
  bomRoles, selectedRole, defaultScopeName, defaultScopeHasItems, selectRole, addRole, renameRole, renameDefaultScope, removeRole,
  quickCopyKeyword, quickCopyLoading,
  quickCopyProgress,
  searchProductsForBom, selectAutocompleteItem, quickCopyBom,
  copyBomDialogVisible, copyBomSearchKeyword, copyBomProducts,
  copyBomSourceProductId, copyBomPreview, copyBomOverwrite, copyBomProgress,
  searchProductForCopy, selectCopyBomProduct, confirmCopyBom,
} = useProductListActions(confirmDialog)

// ===== 角色页签管理：右键菜单（重命名 / 删除角色）+ 内联重命名 =====
// 与 pattern-room RoleTabs 同形态：删除入口不再挂在页签上的「⋯」按钮，改为右键弹出。
type TabKey = Role | 'default'
const roleMenu = ref<{ key: TabKey; x: number; y: number } | null>(null)
const menuTriggerEl = ref<HTMLElement | null>(null)
const menuItemEl = ref<HTMLButtonElement | null>(null)
const renamingTarget = ref<TabKey | null>(null)
const renameInput = ref('')
const renameInputRef = ref<HTMLInputElement | HTMLInputElement[] | null>(null)

/** 关闭菜单；restoreFocus 仅用于键盘路径（不抢鼠标用户刚点的位置） */
function closeMenu(restoreFocus = false) {
  if (!roleMenu.value) return
  roleMenu.value = null
  if (restoreFocus) menuTriggerEl.value?.focus()
}

/** 打开菜单（贴近视口边缘时向内收拢），并把焦点移入首个菜单项 */
async function openRoleMenu(key: TabKey, x: number, y: number, trigger: HTMLElement) {
  const MENU_WIDTH = 148
  const MENU_HEIGHT = 82 // 重命名 + 分隔线 + 删除角色
  const MARGIN = 8
  menuTriggerEl.value = trigger
  roleMenu.value = {
    key,
    // Math.max 兜底：视口比菜单还小时也要留在可点击范围内（不能出负坐标）
    x: Math.max(MARGIN, Math.min(x, window.innerWidth - MENU_WIDTH - MARGIN)),
    y: Math.max(MARGIN, Math.min(y, window.innerHeight - MENU_HEIGHT - MARGIN)),
  }
  await nextTick()
  menuItemEl.value?.focus()
}

function onRoleContextMenu(e: MouseEvent, key: TabKey) {
  e.preventDefault()
  openRoleMenu(key, e.clientX, e.clientY, e.currentTarget as HTMLElement)
}

/**
 * 页签键盘入口。
 *
 * - ContextMenu 键 / Shift+F10 → 打开右键菜单（与 RoleTabs 同）；
 * - Enter / Space → 切换作用域：页签是 div（重命名时要内联渲染 input，button 不能嵌 input），
 *   所以原生按钮的「Enter/Space 触发 click」得显式补上。
 */
function onRoleTabKeydown(e: KeyboardEvent, key: TabKey) {
  if ((e.target as HTMLElement | null)?.closest('input')) return
  // 内联重命名 input 是页签 div 的子节点，keydown 会冒泡到这里。参照页 RoleTabs 的页签是
  // button、内部永远没有 input，所以那边不需要这层判断；这里必须放行——否则空格被
  // preventDefault 吞掉，含空格的角色名（「裁床 1 组」）根本输不进去。
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    selectRole(key === 'default' ? null : key)
    closeMenu()
    return
  }
  if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) {
    e.preventDefault()
    const trigger = e.currentTarget as HTMLElement
    const rect = trigger.getBoundingClientRect()
    openRoleMenu(key, rect.left + 12, rect.bottom + 4, trigger)
  }
}

function onMenuRename() {
  const key = roleMenu.value?.key
  closeMenu(true)
  if (key === undefined) return
  if (key === 'default') startRename('default', defaultScopeName.value)
  else if (bomRoles.value.includes(key)) startRename(key, key.name)
}

function onMenuRemove() {
  const key = roleMenu.value?.key
  closeMenu(true)
  // 菜单打开期间角色可能已被其他操作删掉，别对不存在的角色发起删除
  if (key && key !== 'default' && bomRoles.value.includes(key)) void removeRole(key)
}

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') closeMenu(true)
}

/** 窗口尺寸或滚动变化后菜单会与页签错位，直接关闭 */
function onViewportChange() {
  closeMenu()
}

onMounted(() => {
  document.addEventListener('keydown', onDocumentKeydown)
  window.addEventListener('resize', onViewportChange)
  // scroll 不冒泡，需 capture 才能收到任意滚动容器（含键盘翻页滚动）的事件
  window.addEventListener('scroll', onViewportChange, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onDocumentKeydown)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})

function startRename(key: TabKey, name: string) {
  renamingTarget.value = key
  renameInput.value = name
  closeMenu()
  nextTick(() => {
    const list = Array.isArray(renameInputRef.value) ? renameInputRef.value : [renameInputRef.value]
    list[0]?.focus()
  })
}
async function commitRename() {
  const target = renamingTarget.value
  if (!target) return
  const value = renameInput.value
  // 先收起内联输入，避免 blur 再次触发；再异步提交（全局角色走 PUT，A-13）
  renamingTarget.value = null
  if (target === 'default') renameDefaultScope(value)
  else await renameRole(target, value)
}
function cancelRename() {
  renamingTarget.value = null
}

// ===== 添加角色：与 pattern-room RoleTabs 的「新增角色」同口径 =====
// 常驻图标按钮 → 内联输入框；回车/失焦确认，Esc 取消；trim 后非空才新增。
const addingRole = ref(false)
const newRoleName = ref('')
const roleAddInputRef = ref<HTMLInputElement | null>(null)

async function startAddRole() {
  addingRole.value = true
  newRoleName.value = ''
  await nextTick()
  roleAddInputRef.value?.focus()
}
function commitAddRole() {
  const name = newRoleName.value.trim()
  if (name) addRole(name)
  addingRole.value = false
  newRoleName.value = ''
}
function cancelAddRole() {
  addingRole.value = false
  newRoleName.value = ''
}
// 收起时清空输入（兜底：Esc 后 input 被卸载，不一定再触发 blur）
watch(addingRole, (v) => {
  if (!v) newRoleName.value = ''
})

defineExpose({ open: openBomModal })
</script>

<style scoped>
/* ===== 模态框遮罩 ===== */
.pd-overlay {
  position: fixed; inset: 0; z-index: var(--z-page-modal); background: rgba(0,0,0,0.5);
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

/* ===== 角色页签（点 tab 切换 BOM，⋯ 菜单管理） ===== */
.bom-role-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: white; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 12px;
  padding: 10px 14px; margin-bottom: 16px;
}
.bom-role-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 700; color: var(--color-text); white-space: nowrap;
}
.bom-role-label i { color: var(--color-primary-500); }
.bom-role-tabs { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; flex: 1; }
/* 角色页签外观与 pattern-room RoleTabs 的 .role-tab 逐条同规范
   （用户反馈 m00132：选中/未选中颜色要与参照页一致；默认BOM 不再有独立的虚线灰底） */
.bom-role-tab {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary, #6b7280);
  font-size: 13px; font-family: inherit; font-weight: 500;
  cursor: pointer; transition: all 0.15s ease; user-select: none;
}
.bom-role-tab:hover {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}
.bom-role-tab.active {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-500, #3b82f6), var(--color-primary-600, #2563eb));
  border-color: var(--color-primary-600, #2563eb);
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.25);
}
.bom-role-tab.active:hover {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-600, #2563eb), var(--color-primary-700, #1d4ed8));
}
/* 键盘聚焦时的焦点环（页签可 Tab 聚焦，便于键盘打开右键菜单） */
.bom-role-tab:focus-visible { outline: 2px solid var(--color-primary-400, #60a5fa); outline-offset: 1px; }
.bom-role-name { white-space: nowrap; }
.bom-role-edit-input {
  width: 96px; padding: 2px 8px; border: 1px solid var(--color-primary-400); border-radius: 6px;
  font-size: 13px; font-weight: 600; outline: none; user-select: text;
}
/* 右键菜单：与 pattern-room RoleTabs 的 .role-tab-menu 同规范（遮罩负责点击/滚轮/再次右键关闭） */
.bom-role-menu-mask { position: fixed; inset: 0; z-index: 1000; }
.bom-role-menu {
  position: fixed; z-index: 1001; min-width: 140px; padding: 5px;
  border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 10px;
  background: #fff; box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16);
  animation: role-tab-menu-pop 0.15s ease;
}
/* 与参照页同名：Vue 会把 scoped 样式里的 keyframes 重写为带组件 hash 的名字，跨组件不会互相覆盖 */
@keyframes role-tab-menu-pop { from { transform: scale(0.96) translateY(-4px); opacity: 0; } to { transform: scale(1) translateY(0); opacity: 1; } }
.bom-menu-item {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 10px;
  border: none; border-radius: 7px; background: transparent;
  font-family: inherit; font-size: 13px; font-weight: 600;
  color: var(--color-text-primary); text-align: left; cursor: pointer;
  transition: background 0.14s ease;
}
/* 参照页菜单只有「删除角色」（自带 hover）；这里多了「重命名」，补一条非危险项的 hover */
.bom-menu-item:not(.danger):hover { background: var(--color-primary-50, #eff6ff); }
.bom-menu-item.danger { color: var(--color-danger-600, #d44042); }
.bom-menu-item.danger:hover { background: var(--color-danger-50, #fde8e8); }
/* 菜单项由键盘聚焦时（打开即聚焦）给出可见焦点 */
.bom-menu-item:focus-visible { outline: 2px solid var(--color-primary-400, #60a5fa); outline-offset: -2px; }
.bom-menu-divider { height: 1px; background: var(--color-border-lighter, #f1f5f9); margin: 4px 0; }
.bom-role-empty { font-size: 13px; color: var(--color-text-secondary); }
/* 添加角色：与 pattern-room RoleTabs 的 .role-tab-add / .role-tab-input 同规范 */
.bom-role-add-wrap { display: inline-flex; align-items: center; gap: 4px; }
.bom-role-add-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px;
  border: 1px dashed var(--color-border-light, #e5e7eb); border-radius: 8px;
  background: transparent; color: var(--color-text-secondary, #6b7280);
  cursor: pointer; font-size: 11px; transition: all 0.15s ease;
}
.bom-role-add-btn:hover {
  border-color: var(--color-primary-400, #60a5fa);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}
.bom-role-add-input {
  width: 120px; padding: 6px 10px;
  border: 1px solid var(--color-primary-400, #60a5fa); border-radius: 8px;
  font-size: 13px; font-family: inherit; outline: none;
  box-shadow: 0 0 0 2px var(--color-primary-100, #dbeafe);
}
/* P1-04：当前作用域常驻徽标 */
.bom-scope-badge {
  display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
  padding: 6px 12px; border-radius: 999px; font-size: 12.5px; font-weight: 600;
  color: var(--color-primary-700);
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border: 1px solid var(--color-primary-200);
}
.bom-scope-badge strong { font-weight: 700; }

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

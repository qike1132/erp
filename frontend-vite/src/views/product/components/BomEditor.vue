<template>
  <Teleport to="body">
    <!-- 遮罩层刻意不绑定点击关闭：BOM 配置是长表单，误触弹窗外空白会导致未保存的配置全部丢失。
         关闭入口仅限：① 弹窗右上角关闭按钮 ② 底部「取消」按钮 ③ 保存成功后的自动关闭。
         ①② 都走 requestCloseBom()：有未保存修改时先弹「放弃修改」确认，确认放弃才关闭
         （2026-10-17 审计 F5-5）。请勿为「点遮罩即关」重新加回 @click.self，如需放弃编辑请走显式按钮。 -->
    <div v-if="bomDialogVisible" class="pd-overlay">
      <div class="bom-modal-content bom-modal-dialog">
        <div class="bom-modal-header">
          <div class="bom-modal-header-left">
            <h5 class="bom-modal-title"><FontAwesomeIcon icon="cogs" aria-hidden="true" /><span>BOM表配置 - {{ bomProductName }}</span></h5>
          </div>
          <button class="bom-modal-close" aria-label="关闭" @click="requestCloseBom()"><FontAwesomeIcon icon="times" aria-hidden="true" /></button>
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
          <button class="bom-btn-cancel" @click="requestCloseBom()">取消</button>
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
  requestCloseBom, bomDirty,
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
// ⚠️ F1b-09（2026-10-24 审计）：两套并行实现仅靠注释人工同步，已存在行为分叉
// （本文件菜单多「重命名」、keydown 处理多一处冒泡特判）——改任一侧必须逐行
// 核对另一侧（frontend-vite/src/views/pattern-room/components/RoleTabs.vue），
// 或抽公共 useContextMenu/RoleTabsBase 抽象。
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

defineExpose({ open: openBomModal, bomDirty })
</script>

<style scoped src="./BomEditor.css"></style>

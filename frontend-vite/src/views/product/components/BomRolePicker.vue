<template>
  <div ref="rootRef" class="brp-wrap">
    <button type="button" class="brp-trigger" :class="{ active: open }" @click="toggle">
      <FontAwesomeIcon icon="tags" aria-hidden="true" /> 选择已有角色
      <FontAwesomeIcon class="brp-caret" :icon="open ? 'chevron-up' : 'chevron-down'" aria-hidden="true" />
    </button>

    <div v-if="open" class="brp-panel" role="dialog" aria-label="全局角色字典" @click.stop>
      <div class="brp-head">
        <input
          v-model="keyword"
          class="brp-input"
          type="text"
          maxlength="100"
          placeholder="搜索全局角色名"
          autocomplete="off"
        />
        <button type="button" class="brp-btn" :disabled="loading" @click="load">刷新</button>
      </div>

      <div v-if="loading" class="brp-hint">加载中…</div>
      <div v-else-if="!filtered.length" class="brp-hint">
        {{ allRoles.length ? '无匹配角色' : '暂无全局角色，可用左侧「添加角色」新建' }}
      </div>
      <ul v-else class="brp-list">
        <li v-for="role in filtered" :key="role.id" class="brp-item">
          <template v-if="editingId === role.id">
            <input
              ref="editInputRef"
              v-model="editName"
              class="brp-input brp-edit"
              type="text"
              maxlength="100"
              @keydown.enter.prevent="commitRename(role)"
              @keydown.esc.prevent="cancelRename"
              @blur="commitRename(role)"
            />
          </template>
          <template v-else>
            <span class="brp-name" :title="role.name">{{ role.name }}</span>
            <span class="brp-actions">
              <span v-if="isAssociated(role.id)" class="brp-linked">已关联</span>
              <button
                v-else
                type="button"
                class="brp-btn primary"
                @click="associate(role)"
              >关联</button>
              <button type="button" class="brp-btn icon" title="重命名" @click="startRename(role)">
                <FontAwesomeIcon icon="pencil-alt" aria-hidden="true" />
              </button>
              <button type="button" class="brp-btn icon danger" title="从字典删除" @click="remove(role)">
                <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
              </button>
            </span>
          </template>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { showToast } from '@/composables/useToast'
import {
  roleApi,
  isRoleNameConflictError,
  isRoleReferencedError,
  type RoleItem,
} from '@/api/role'

/**
 * 全局角色选择器（BOM 编辑器的「全局角色入口」）。
 *
 * 提供：列出全局角色字典 / 关联到当前产品 / 重命名（PUT）/ 删除（DELETE）。
 * - 关联：仅建立产品关联行，**不复制**全局角色记录（A-1）；
 * - 重命名：走 `PUT /purchase-center/roles/{id}`，不改物料归属（A-13）；
 * - 删除：走 `DELETE /purchase-center/roles/{id}`，被引用（409）时把后端 detail
 *   （含引用数）直接呈现给用户（A-14）。
 *
 * 新建角色不在此处：仍由角色栏「添加角色」走 `role_key` 路径（需求 §T05-2）。
 */
const props = withDefaults(defineProps<{ associatedGlobalIds?: number[] }>(), {
  associatedGlobalIds: () => [],
})

const emit = defineEmits<{
  /** 关联某个全局角色到当前产品。 */
  (e: 'associate', role: RoleItem): void
  /** 全局角色已重命名（同步本地关联角色名）。 */
  (e: 'renamed', payload: { id: number; name: string }): void
  /** 全局角色已从字典删除。 */
  (e: 'deleted', id: number): void
}>()

const rootRef = ref<HTMLElement | null>(null)
const open = ref(false)
const loading = ref(false)
const keyword = ref('')
const allRoles = ref<RoleItem[]>([])
const loaded = ref(false)

const editingId = ref<number | null>(null)
const editName = ref('')
const editInputRef = ref<HTMLInputElement | HTMLInputElement[] | null>(null)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return allRoles.value
  return allRoles.value.filter(role => role.name.toLowerCase().includes(kw))
})

function isAssociated(globalRoleId: number): boolean {
  return props.associatedGlobalIds.includes(globalRoleId)
}

async function load() {
  loading.value = true
  try {
    allRoles.value = await roleApi.list()
    loaded.value = true
  } catch (error) {
    showToast('加载全局角色失败', 'error')
  } finally {
    loading.value = false
  }
}

function toggle() {
  open.value = !open.value
  if (open.value && !loaded.value) load()
}

function close() {
  open.value = false
  editingId.value = null
}

function associate(role: RoleItem) {
  emit('associate', role)
}

function startRename(role: RoleItem) {
  editingId.value = role.id
  editName.value = role.name
  nextTick(() => {
    const list = Array.isArray(editInputRef.value) ? editInputRef.value : [editInputRef.value]
    list[0]?.focus()
  })
}

function cancelRename() {
  editingId.value = null
}

async function commitRename(role: RoleItem) {
  const id = editingId.value
  if (id == null) return
  const name = (editName.value || '').trim()
  editingId.value = null
  if (!name || name === role.name) return
  try {
    const updated = await roleApi.rename(id, name)
    role.name = updated?.name || name
    showToast('角色已重命名', 'success')
    emit('renamed', { id, name: role.name })
  } catch (error) {
    if (isRoleNameConflictError(error)) {
      showToast((error as { detail?: string }).detail || '角色名称已存在', 'warning')
    } else {
      showToast('重命名角色失败', 'error')
    }
  }
}

async function remove(role: RoleItem) {
  try {
    const message = await roleApi.remove(role.id)
    allRoles.value = allRoles.value.filter(item => item.id !== role.id)
    showToast(message || `已删除角色「${role.name}」`, 'success')
    emit('deleted', role.id)
  } catch (error) {
    if (isRoleReferencedError(error)) {
      // A-14：直接呈现后端 detail（含被引用产品数），友好提示先解绑
      showToast((error as { detail?: string }).detail || '该角色已被产品引用，无法删除；请先解绑', 'warning')
    } else if (isRoleNameConflictError(error)) {
      showToast((error as { detail?: string }).detail || '角色名称冲突', 'warning')
    } else {
      showToast('删除角色失败', 'error')
    }
  }
}

function onDocumentClick(event: MouseEvent) {
  if (!open.value) return
  // 面板内点击已被根节点 @click.stop 拦截，不会到达这里；此处两道防御：
  // 1) 脱离文档树的 target 直接忽略 —— 真实鼠标点击面板内按钮时，该按钮的
  //    自身处理器返回后浏览器会执行一次 microtask 检查点，Vue 队列里的重渲染
  //    随即把它换成别的节点；等事件冒泡到 document 时 event.target 已 isConnected=false，
  //    若仍按 contains 判定会被误判为「点击面板外」而关闭面板（D-1）。
  //    （编程式 el.click() 在脚本栈内同步派发，不会触发该检查点，故不复现。）
  // 2) 正常面板外点击的节点仍在文档树中，照常走 contains 关闭。
  if (!(event.target instanceof Node) || !event.target.isConnected) return
  const el = rootRef.value
  if (el && !el.contains(event.target)) close()
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))
</script>

<style scoped>
.brp-wrap { position: relative; display: inline-flex; }
.brp-trigger {
  display: inline-flex; align-items: center; gap: 6px;
  border: 2px dashed var(--color-primary-200); background: var(--color-primary-50);
  color: var(--color-primary-600); border-radius: 9px; padding: 7px 14px;
  font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s ease;
}
.brp-trigger:hover, .brp-trigger.active { border-color: var(--color-primary-400); background: var(--color-primary-100); }
.brp-caret { font-size: 10px; opacity: 0.7; }

.brp-panel {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: 40; width: 320px;
  background: #fff; border: 1px solid var(--color-border-light, #e2e8f0); border-radius: 12px;
  box-shadow: 0 16px 40px rgba(15,23,42,.16); padding: 10px;
  animation: brp-pop 0.15s ease;
}
@keyframes brp-pop { from { transform: translateY(-4px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
.brp-head { display: flex; gap: 8px; margin-bottom: 8px; }
.brp-input {
  flex: 1; min-width: 0; padding: 6px 10px; border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px; font-size: 13px; outline: none;
}
.brp-input:focus { border-color: var(--color-primary-400); box-shadow: 0 0 0 3px rgba(0,148,191,.1); }
.brp-list { list-style: none; margin: 0; padding: 0; max-height: 260px; overflow-y: auto; }
.brp-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 6px 8px; border-radius: 8px;
}
.brp-item:hover { background: var(--color-surface, #f8fafc); }
.brp-name { flex: 1; min-width: 0; font-size: 13px; font-weight: 600; color: var(--color-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.brp-actions { display: inline-flex; align-items: center; gap: 4px; }
.brp-linked { font-size: 12px; color: var(--color-text-secondary); }
.brp-btn {
  border: 1px solid var(--color-border-light, #e2e8f0); background: #fff; color: var(--color-text);
  border-radius: 7px; padding: 4px 10px; font-size: 12px; font-weight: 600; cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.brp-btn:hover:not(:disabled) { background: var(--color-surface, #f8fafc); }
.brp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.brp-btn.primary { background: var(--color-primary-50); border-color: var(--color-primary-200); color: var(--color-primary-600); }
.brp-btn.icon { padding: 4px 7px; }
.brp-btn.danger { color: var(--color-danger-600); border-color: var(--color-danger-50); }
.brp-btn.danger:hover { background: var(--color-danger-50); }
.brp-edit { width: 100%; }
.brp-hint { padding: 10px 8px; font-size: 13px; color: var(--color-text-secondary); text-align: center; }
</style>

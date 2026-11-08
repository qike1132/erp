import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { showToast } from '@/composables/useToast'
import type { Role } from './bomTypes'

type TabKey = Role | 'default'

interface BomRoleMenuActions {
  bomRoles: Ref<Role[]>
  defaultScopeName: Ref<string>
  selectRole: (role: Role | null) => void
  addRole: (name: string) => void
  renameRole: (role: Role, name: string) => boolean
  renameDefaultScope: (name: string) => void
  removeRole: (role: Role) => Promise<void>
}

/** BOM 角色页签的右键菜单、键盘交互与内联新增/重命名。 */
export function useBomRoleMenu(actions: BomRoleMenuActions) {
  const roleMenu = ref<{ key: TabKey; x: number; y: number } | null>(null)
  const menuTriggerEl = ref<HTMLElement | null>(null)
  const menuItemEl = ref<HTMLButtonElement | null>(null)
  const renamingTarget = ref<TabKey | null>(null)
  const renameInput = ref('')
  const renameInputRef = ref<HTMLInputElement | HTMLInputElement[] | null>(null)
  const addingRole = ref(false)
  const newRoleName = ref('')
  const roleAddInputRef = ref<HTMLInputElement | null>(null)

  function closeMenu(restoreFocus = false) {
    if (!roleMenu.value) return
    roleMenu.value = null
    if (restoreFocus) menuTriggerEl.value?.focus()
  }

  async function openRoleMenu(key: TabKey, x: number, y: number, trigger: HTMLElement) {
    // 菜单现有三项：重命名 / 指定（取消）隐藏款 / 删除角色 —— 高度按三行 + 分隔线留足
    const MENU_WIDTH = 176
    const MENU_HEIGHT = 132
    const MARGIN = 8
    menuTriggerEl.value = trigger
    roleMenu.value = {
      key,
      x: Math.max(MARGIN, Math.min(x, window.innerWidth - MENU_WIDTH - MARGIN)),
      y: Math.max(MARGIN, Math.min(y, window.innerHeight - MENU_HEIGHT - MARGIN)),
    }
    await nextTick()
    menuItemEl.value?.focus()
  }

  function onRoleContextMenu(event: MouseEvent, key: TabKey) {
    event.preventDefault()
    void openRoleMenu(key, event.clientX, event.clientY, event.currentTarget as HTMLElement)
  }

  function onRoleTabKeydown(event: KeyboardEvent, key: TabKey) {
    if ((event.target as HTMLElement | null)?.closest('input')) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      actions.selectRole(key === 'default' ? null : key)
      closeMenu()
      return
    }
    if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
      event.preventDefault()
      const trigger = event.currentTarget as HTMLElement
      const rect = trigger.getBoundingClientRect()
      void openRoleMenu(key, rect.left + 12, rect.bottom + 4, trigger)
    }
  }

  function startRename(key: TabKey, name: string) {
    renamingTarget.value = key
    renameInput.value = name
    closeMenu()
    void nextTick(() => {
      const list = Array.isArray(renameInputRef.value) ? renameInputRef.value : [renameInputRef.value]
      list[0]?.focus()
    })
  }

  function onMenuRename() {
    const key = roleMenu.value?.key
    closeMenu(true)
    if (key === undefined) return
    if (key === 'default') startRename('default', actions.defaultScopeName.value)
    else if (actions.bomRoles.value.includes(key)) startRename(key, key.name)
  }

  function onMenuRemove() {
    const key = roleMenu.value?.key
    closeMenu(true)
    if (key && key !== 'default' && actions.bomRoles.value.includes(key)) void actions.removeRole(key)
  }

  /**
   * 指定 / 取消隐藏款（本地改，保存 BOM 时随 payload 落库）。
   *
   * 每个 SKU 只允许一个隐藏款：指定新角色时先把其余角色的标记清掉，
   * 并提示被替换的原隐藏款（需求：重复指定需提示或自动替换——两者都做）。
   */
  function onMenuToggleHidden() {
    const key = roleMenu.value?.key
    closeMenu(true)
    if (!key || key === 'default') return
    if (!actions.bomRoles.value.includes(key)) return
    if (key.is_hidden === true) {
      key.is_hidden = false
      showToast(`已取消「${key.name}」的隐藏款标记`, 'success')
      return
    }
    const previous = actions.bomRoles.value.find((role) => role !== key && role.is_hidden === true)
    actions.bomRoles.value.forEach((role) => { role.is_hidden = false })
    key.is_hidden = true
    showToast(
      previous
        ? `已将「${key.name}」设为隐藏款，原隐藏款「${previous.name}」已自动取消`
        : `已将「${key.name}」设为隐藏款`,
      'success',
    )
  }

  async function commitRename() {
    const target = renamingTarget.value
    if (!target) return
    const value = renameInput.value
    renamingTarget.value = null
    if (target === 'default') actions.renameDefaultScope(value)
    else await actions.renameRole(target, value)
  }

  function cancelRename() {
    renamingTarget.value = null
  }

  async function startAddRole() {
    addingRole.value = true
    newRoleName.value = ''
    await nextTick()
    roleAddInputRef.value?.focus()
  }

  function commitAddRole() {
    const name = newRoleName.value.trim()
    if (name) actions.addRole(name)
    addingRole.value = false
    newRoleName.value = ''
  }

  function cancelAddRole() {
    addingRole.value = false
    newRoleName.value = ''
  }

  function onDocumentKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') closeMenu(true)
  }

  function onViewportChange() {
    closeMenu()
  }

  onMounted(() => {
    document.addEventListener('keydown', onDocumentKeydown)
    window.addEventListener('resize', onViewportChange)
    window.addEventListener('scroll', onViewportChange, true)
  })
  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onDocumentKeydown)
    window.removeEventListener('resize', onViewportChange)
    window.removeEventListener('scroll', onViewportChange, true)
  })
  watch(addingRole, (visible) => {
    if (!visible) newRoleName.value = ''
  })

  return {
    roleMenu, menuItemEl, renamingTarget, renameInput, renameInputRef,
    addingRole, newRoleName, roleAddInputRef,
    closeMenu, onRoleContextMenu, onRoleTabKeydown, onMenuRename, onMenuRemove,
    onMenuToggleHidden,
    commitRename, cancelRename, startAddRole, commitAddRole, cancelAddRole,
  }
}

import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
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
    const MENU_WIDTH = 148
    const MENU_HEIGHT = 82
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
    commitRename, cancelRename, startAddRole, commitAddRole, cancelAddRole,
  }
}

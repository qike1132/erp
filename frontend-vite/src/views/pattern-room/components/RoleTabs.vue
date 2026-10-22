<template>
  <div v-if="roles.length > 0 || canManage" class="role-tabs">
    <button
      v-for="role in roles"
      :key="role.id"
      type="button"
      :class="['role-tab', { 'role-tab--active': role.id === activeRoleId }]"
      :title="canManage ? '右键打开菜单' : undefined"
      :aria-haspopup="canManage ? 'menu' : undefined"
      :aria-expanded="canManage ? menu?.role.id === role.id : undefined"
      @click="$emit('select', role.id)"
      @contextmenu="onContextMenu($event, role)"
      @keydown="onTabKeydown($event, role)"
    >
      <span class="role-tab-name">
        {{ role.role_name }}
      </span>
    </button>
    <button
      v-if="canManage"
      type="button"
      class="role-tab-add"
      title="新增角色"
      aria-label="新增角色"
      @click="onAddClick"
    >
      <FontAwesomeIcon icon="plus" aria-hidden="true" />
    </button>

    <!-- 新增角色内联输入 -->
    <div v-if="adding" class="role-tab-input-wrap" @click.stop>
      <input
        ref="inputEl"
        v-model="newName"
        class="role-tab-input"
        placeholder="角色名称"
        aria-label="新角色名称"
        maxlength="100"
        @keydown.enter="onAddConfirm"
        @keydown.esc="onAddCancel"
        @blur="onAddConfirm"
      />
    </div>

    <!-- 行尾操作区（录入信息/打印等，推至最右）；无角色时部位录入等操作无从归属，不展示 -->
    <div v-if="roles.length > 0 && $slots.actions" class="role-tabs-actions">
      <slot name="actions" />
    </div>

    <!-- 右键菜单：删除角色（替代标签上的 × 按钮，避免误点） -->
    <div
      v-if="menu"
      class="role-tab-menu-mask"
      @click="closeMenu()"
      @contextmenu.prevent="closeMenu()"
      @wheel="closeMenu()"
    />
    <div
      v-if="menu"
      class="role-tab-menu"
      role="menu"
      aria-label="角色操作"
      :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
      @keydown="onMenuKeydown"
    >
      <button ref="menuItemEl" type="button" role="menuitem" class="role-tab-menu-item danger" @click="onMenuRemove">
        <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
        删除角色
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch, onMounted, onBeforeUnmount } from 'vue'
import type { RoleBrief } from '@/api/patternRoom'

const props = defineProps<{
  roles: RoleBrief[]
  currentRoleId: number | null
  canManage: boolean
}>()

/**
 * 有效激活角色。useSamplingRole 在切项目时会先清空 currentRoleId、再异步拉角色列表，
 * 接口在途期间 currentRoleId 为 null → 若直接用它判断，标签会先渲染成未选中（白）再变蓝。
 * 按该 hook「默认选中第一个角色」的口径回退到首个，消除这次闪烁。
 */
const activeRoleId = computed(() => props.currentRoleId ?? props.roles[0]?.id ?? null)

const emit = defineEmits<{
  select: [roleId: number]
  add: [roleName: string]
  remove: [role: RoleBrief]
}>()

const adding = ref(false)
const newName = ref('')
const inputEl = ref<HTMLInputElement | null>(null)

async function onAddClick() {
  adding.value = true
  newName.value = ''
  await nextTick()
  inputEl.value?.focus()
}

function onAddConfirm() {
  const name = newName.value.trim()
  if (name) {
    emit('add', name)
  }
  adding.value = false
  newName.value = ''
}

function onAddCancel() {
  adding.value = false
  newName.value = ''
}

// adding 关闭时清空输入（兜底）
watch(adding, (v) => {
  if (!v) newName.value = ''
})

/** 右键菜单：菜单坐标 + 目标角色；triggerEl 用于关闭后归还焦点 */
const menu = ref<{ role: RoleBrief; x: number; y: number } | null>(null)
const triggerEl = ref<HTMLElement | null>(null)
const menuItemEl = ref<HTMLButtonElement | null>(null)

/** 关闭菜单；restoreFocus 仅用于键盘路径（Esc/激活菜单项），不抢鼠标用户刚点的位置 */
function closeMenu(restoreFocus = false) {
  if (!menu.value) return
  menu.value = null
  if (restoreFocus) triggerEl.value?.focus()
}

/** 打开菜单（贴近视口边缘时向内收拢，避免被裁掉），并把焦点移入首个菜单项 */
async function openMenu(role: RoleBrief, x: number, y: number, trigger: HTMLElement) {
  const MENU_WIDTH = 148
  const MENU_HEIGHT = 42
  const MARGIN = 8
  triggerEl.value = trigger
  menu.value = {
    role,
    // Math.max 兜底：视口比菜单还小时也要留在可点击范围内（不能出负坐标）
    x: Math.max(MARGIN, Math.min(x, window.innerWidth - MENU_WIDTH - MARGIN)),
    y: Math.max(MARGIN, Math.min(y, window.innerHeight - MENU_HEIGHT - MARGIN)),
  }
  await nextTick()
  menuItemEl.value?.focus()
}

function onContextMenu(e: MouseEvent, role: RoleBrief) {
  // 无权限：不接管，走浏览器原生菜单
  if (!props.canManage) return
  e.preventDefault()
  openMenu(role, e.clientX, e.clientY, e.currentTarget as HTMLElement)
}

/** 键盘入口：Enter/Space 由原生按钮触发 click，这里只处理菜单键与 Shift+F10 */
function onTabKeydown(e: KeyboardEvent, role: RoleBrief) {
  if (!props.canManage) return
  if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) {
    e.preventDefault()
    const trigger = e.currentTarget as HTMLElement
    const rect = trigger.getBoundingClientRect()
    openMenu(role, rect.left + 12, rect.bottom + 4, trigger)
  }
}

function onMenuRemove() {
  const role = menu.value?.role
  closeMenu(true)
  // 菜单打开期间角色可能已被其他操作删掉，别对不存在的角色发起删除
  if (role && props.roles.some((r) => r.id === role.id)) emit('remove', role)
}

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') closeMenu(true)
}

/**
 * 菜单内键盘处理（APG menu 约定，审查 A11Y-19）。
 * Tab：关闭菜单并把焦点交还触发元素 —— 否则菜单项被 v-if 移除后焦点掉到 body，
 * 且遮罩层仍在，用户会对着一个「点不动」的界面继续 Tab。
 * 方向键 / Home / End：当前菜单只有一项，无项可移，仅阻止页面跟着滚动。
 */
function onMenuKeydown(e: KeyboardEvent) {
  if (e.key === 'Tab') {
    e.preventDefault()
    closeMenu(true)
    return
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
    e.preventDefault()
  }
}

/** 窗口尺寸或滚动变化后菜单会与标签错位，直接关闭 */
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
</script>

<style scoped>
.role-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  flex-wrap: wrap;
}

/* 行尾操作区：推至同一行最右边 */
.role-tabs-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.role-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary, #6b7280);
  font-size: 13px;
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  user-select: none;
}

.role-tab:hover {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}

.role-tab--active {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-500, #3b82f6), var(--color-primary-600, #2563eb));
  border-color: var(--color-primary-600, #2563eb);
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.25);
}

.role-tab--active:hover {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-600, #2563eb), var(--color-primary-700, #1d4ed8));
}

.role-tab-name {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* 键盘聚焦时的焦点环（标签可 Tab 聚焦，便于键盘打开右键菜单） */
.role-tab:focus-visible {
  outline: 2px solid var(--color-primary-400, #60a5fa);
  outline-offset: 1px;
}

/* 右键菜单：遮罩层负责点击/滚轮/再次右键关闭 */
.role-tab-menu-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
}

.role-tab-menu {
  position: fixed;
  z-index: 1001;
  min-width: 140px;
  padding: 5px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16);
  animation: role-tab-menu-pop 0.15s ease;
}

@keyframes role-tab-menu-pop {
  from {
    transform: scale(0.96) translateY(-4px);
    opacity: 0;
  }
  to {
    transform: scale(1) translateY(0);
    opacity: 1;
  }
}

.role-tab-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
  text-align: left;
  cursor: pointer;
  transition: background 0.14s ease;
}

.role-tab-menu-item.danger {
  color: var(--color-danger-600, #d44042);
}

.role-tab-menu-item.danger:hover {
  background: var(--color-danger-50, #fde8e8);
}

/* 菜单项由键盘聚焦时（打开即聚焦）给出可见焦点 */
.role-tab-menu-item:focus-visible {
  outline: 2px solid var(--color-primary-400, #60a5fa);
  outline-offset: -2px;
}

.role-tab-add {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px dashed var(--color-border-light, #e5e7eb);
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary, #6b7280);
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 11px;
}

.role-tab-add:hover {
  border-color: var(--color-primary-400, #60a5fa);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}

.role-tab-input-wrap {
  display: inline-flex;
  align-items: center;
}

.role-tab-input {
  width: 120px;
  padding: 6px 10px;
  border: 1px solid var(--color-primary-400, #60a5fa);
  border-radius: 8px;
  font-size: 13px;
  font-family: inherit;
  box-shadow: 0 0 0 2px var(--color-primary-100, #dbeafe);
}
</style>

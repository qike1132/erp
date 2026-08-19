<template>
  <div class="page-card-toolbar">
    <div class="page-toolbar-left">
      <button class="menu-toggle-btn" aria-label="切换侧边栏" @click="sidebarStore.toggle()">
        <FontAwesomeIcon :icon="!sidebarStore.isCollapsed ? 'angles-left' : 'angles-right'" style="font-size: 18px" aria-hidden="true" />
      </button>
    </div>
    <div class="page-toolbar-right">
      <div class="tb-cluster">
        <span class="tb-time">
          <FontAwesomeIcon icon="clock" aria-hidden="true" />
          {{ currentTime }}
        </span>
        <span class="tb-divider" aria-hidden="true" />
        <NotificationBell v-if="authStore.isLoggedIn" />
        <span class="tb-divider" aria-hidden="true" />
        <div class="tb-user">
          <div class="tb-avatar" aria-hidden="true">{{ avatarLetter }}</div>
          <div class="tb-user-text min-w-0">
            <div class="tb-name">{{ authStore.user?.username || '用户' }}</div>
            <div class="tb-role">{{ authStore.user?.is_super ? '超级管理员' : '普通用户' }}</div>
          </div>
        </div>
        <button class="tb-logout" @click="confirmLogout" aria-label="退出登录">
          <FontAwesomeIcon icon="right-from-bracket" aria-hidden="true" />
          <span>退出</span>
        </button>
      </div>
    </div>
  </div>

  <UiConfirmDialog
    :open="logoutConfirm.open"
    :text="logoutConfirm.text"
    :sub="logoutConfirm.sub"
    :type="logoutConfirm.type"
    @confirm="logoutConfirm.onConfirm"
    @cancel="logoutConfirm.onCancel"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import NotificationBell from '@/layouts/components/NotificationBell.vue'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useSidebarStore } from '@/stores/sidebar'
import { useConfirmDialog } from '@/composables/useConfirmDialog'

defineProps<{
  currentTime: string
}>()

const authStore = useAuthStore()
const sidebarStore = useSidebarStore()
const logoutConfirm = useConfirmDialog()
const router = useRouter()
const avatarLetter = computed(() => (authStore.user?.username || 'U').charAt(0).toUpperCase())

async function handleLogout() {
  try {
    await authApi.logout()
  } finally {
    authStore.logout()
    router.push('/login')
  }
}

async function confirmLogout() {
  const ok = await logoutConfirm.confirm('确定要退出登录吗？', '退出后需重新登录', 'danger')
  if (ok) handleLogout()
}
</script>

<style scoped>
.menu-toggle-btn {
  background: var(--color-surface-card);
  border: 2px solid var(--color-ocean);
  color: var(--color-text);
  width: 44px;
  height: 44px;
  border-radius: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: transform 0.2s ease, background 0.2s ease;
  box-shadow: 0 2px 8px rgba(176, 224, 230, 0.25);
  will-change: transform;
}

.menu-toggle-btn:hover {
  background: var(--color-ocean-light);
  transform: scale(1.05);
}

.tb-cluster {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px 4px 14px;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95) 0%, rgba(240, 244, 248, 0.95) 100%);
  border: 2px solid var(--color-ocean-light);
  box-shadow:
    0 2px 12px color-mix(in srgb, var(--color-ocean) 22%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition:
    transform 0.3s cubic-bezier(0.4, 0, 0.2, 1),
    border-color 0.3s ease,
    box-shadow 0.3s ease;
}
.tb-cluster:hover {
  transform: translateY(-1px);
  border-color: var(--color-ocean-deep);
  box-shadow:
    0 6px 20px color-mix(in srgb, var(--color-ocean) 35%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 1);
}

.tb-time {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-tertiary);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.tb-divider {
  width: 1px;
  height: 22px;
  margin: 0 4px;
  background: var(--color-border-light);
}

.tb-user {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 2px 4px;
}

.tb-avatar {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--color-ocean) 0%, var(--color-ocean-deep) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-inverse);
  font-weight: 700;
  font-size: 14px;
  box-shadow: 0 3px 10px color-mix(in srgb, var(--color-ocean) 25%, transparent);
  flex-shrink: 0;
}

.tb-user-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.tb-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1.2;
}

.tb-role {
  font-size: 11px;
  color: var(--color-text-tertiary);
  opacity: 0.85;
  line-height: 1.2;
}

.tb-logout {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 12px;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: var(--color-danger-700);
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.2s ease, color 0.2s ease;
}
.tb-logout:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-800);
}

@media (max-width: 768px) {
  .tb-time {
    display: none;
  }
}
</style>
<template>
  <div class="m-nb-root">
    <button
      type="button"
      class="m-nb-btn"
      :class="{ 'has-unread': unreadCount > 0 }"
      :aria-label="`通知中心，${unreadCount} 条未读`"
      @click="goToCenter"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
      <span v-if="unreadCount > 0" class="m-nb-badge">{{ displayCount }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useNotifications } from '@/composables/useNotifications'

const router = useRouter()
const { unreadCount, startPolling, stopPolling } = useNotifications()

const displayCount = computed(() => (unreadCount.value > 99 ? '99+' : String(unreadCount.value)))

function goToCenter() {
  router.push('/notifications')
}

onMounted(() => {
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.m-nb-root {
  position: fixed;
  top: calc(var(--m-safe-top, 0px) + 4px);
  right: 8px;
  z-index: 60;
}

.m-nb-btn {
  position: relative;
  width: 36px;
  height: 36px;
  border-radius: 11px;
  border: none;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px) saturate(180%);
  -webkit-backdrop-filter: blur(12px) saturate(180%);
  color: var(--m-text-primary, #1a1a2e);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
  -webkit-tap-highlight-color: transparent;
  transition: transform 0.2s var(--m-ease-spring, ease);
}

.m-nb-btn:active {
  transform: scale(0.9);
}

.m-nb-btn.has-unread {
  color: var(--m-accent, #0071E3);
}

.m-nb-badge {
  position: absolute;
  top: 0;
  right: 0;
  transform: translate(35%, -35%);
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: linear-gradient(135deg, #ed5657, #ea5455);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(234, 84, 85, 0.35);
  border: 1.5px solid #fff;
  white-space: nowrap;
  box-sizing: border-box;
  pointer-events: none;
}
</style>
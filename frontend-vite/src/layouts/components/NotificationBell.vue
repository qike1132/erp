<template>
  <div class="nb-root">
    <button
      type="button"
      class="nb-bell"
      :class="{ 'has-badge': unreadCount > 0 }"
      :aria-label="`通知中心，${unreadCount} 条未读`"
      @click="goToCenter"
    >
      <FontAwesomeIcon icon="bell" aria-hidden="true" />
      <span v-if="unreadCount > 0" class="nb-badge">{{ displayCount }}</span>
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
.nb-root {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.nb-bell {
  position: relative;
  padding: 10px 16px;
  height: auto;
  min-height: 40px;
  min-width: 44px;
  border-radius: 14px;
  border: 2px solid var(--color-primary-200);
  background: linear-gradient(135deg, var(--color-primary-50) 0%, var(--color-primary-100) 100%);
  color: var(--color-primary-700);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 700;
  box-shadow:
    0 2px 6px color-mix(in srgb, var(--color-primary-200) 35%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.6);
  transition:
    background 0.3s ease,
    color 0.3s ease,
    box-shadow 0.3s ease,
    transform 0.3s ease,
    border-color 0.3s ease;
  -webkit-tap-highlight-color: transparent;
}

.nb-bell:hover {
  color: var(--color-primary-800);
  border-color: var(--color-primary-300);
  background: linear-gradient(135deg, var(--color-primary-100) 0%, var(--color-primary-200) 100%);
  transform: translateY(-2px);
  box-shadow:
    0 6px 18px color-mix(in srgb, var(--color-primary-200) 45%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.nb-badge {
  position: absolute;
  top: 0;
  right: 0;
  transform: translate(35%, -35%);
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: linear-gradient(135deg, var(--color-danger-400), var(--color-danger-600));
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(234, 84, 85, 0.35);
  border: 1.5px solid var(--color-surface-card);
  pointer-events: none;
  white-space: nowrap;
  box-sizing: border-box;
}
</style>
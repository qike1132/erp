<template>
  <div class="nb-root">
    <button
      type="button"
      class="nb-btn"
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

/* 扁平图标按钮：用于融入统一工具栏胶囊，不单独成块 */
.nb-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 15px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}
.nb-btn:hover {
  background: var(--color-ocean-light);
  color: var(--color-ocean-text);
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
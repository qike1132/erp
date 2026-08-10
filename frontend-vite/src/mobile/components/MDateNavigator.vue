<template>
  <div class="m-date-nav" role="navigation" aria-label="日期导航">
    <button class="m-date-nav-btn" :disabled="disabled" aria-label="前一天" @click="onPrev">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="18" height="18">
        <polyline points="15 18 9 12 15 6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    <div class="m-date-nav-display" @click="onDateClick">
      <span class="m-date-nav-label">{{ formattedDate }}</span>
      <span v-if="subtitle" class="m-date-nav-sub">{{ subtitle }}</span>
    </div>

    <button class="m-date-nav-btn" :disabled="disabled" aria-label="后一天" @click="onNext">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="18" height="18">
        <polyline points="9 18 15 12 9 6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  date: Date
  subtitle?: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'prev'): void
  (e: 'next'): void
  (e: 'dateClick'): void
}>()

const formattedDate = computed(() => {
  const d = props.date
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diff = (target.getTime() - today.getTime()) / 86400000

  const year = d.getFullYear()
  const month = d.getMonth() + 1
  const day = d.getDate()
  const weekDays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  const weekday = weekDays[d.getDay()]

  if (diff === 0) return `今天 ${month}月${day}日 ${weekday}`
  if (diff === -1) return `昨天 ${month}月${day}日 ${weekday}`
  if (diff === 1) return `明天 ${month}月${day}日 ${weekday}`
  return `${year}年${month}月${day}日 ${weekday}`
})

function onPrev() {
  if (!props.disabled) emit('prev')
}
function onNext() {
  if (!props.disabled) emit('next')
}
function onDateClick() {
  emit('dateClick')
}
</script>

<style scoped>
.m-date-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0;
  gap: 8px;
}

.m-date-nav-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: var(--m-bg-surface);
  border-radius: var(--m-radius-md);
  color: var(--m-text-primary);
  cursor: pointer;
  transition: opacity 0.15s var(--m-ease-smooth), transform 0.15s var(--m-ease-smooth);
  -webkit-tap-highlight-color: transparent;
  box-shadow: var(--m-shadow-soft);
}

.m-date-nav-btn:active {
  transform: scale(0.92);
}
.m-date-nav-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

.m-date-nav-display {
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  user-select: none;
}

.m-date-nav-label {
  font-size: var(--m-font-title);
  font-weight: var(--m-font-weight-bold);
  color: var(--m-text-primary);
  line-height: 1.2;
}

.m-date-nav-sub {
  font-size: var(--m-font-label-sm);
  color: var(--m-text-secondary);
  margin-top: 2px;
}
</style>

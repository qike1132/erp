<template>
  <div :class="['m-list-item', { clickable: !!to, active }]" @click="handleClick">
    <div v-if="$slots.icon" class="m-list-item-icon">
      <slot name="icon" />
    </div>
    <div class="m-list-item-body">
      <div class="m-list-item-title">{{ title }}</div>
      <div v-if="subtitle" class="m-list-item-subtitle">{{ subtitle }}</div>
    </div>
    <div v-if="$slots.value" class="m-list-item-value">
      <slot name="value" />
    </div>
    <div v-if="$slots.accessory" class="m-list-item-accessory">
      <slot name="accessory" />
    </div>
    <svg v-if="to" class="m-list-item-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const props = defineProps<{
  title: string
  subtitle?: string
  to?: string
  active?: boolean
}>()

const router = useRouter()

function handleClick() {
  if (props.to) {
    router.push(props.to)
  }
}
</script>

<style scoped>
.m-list-item {
  display: flex;
  align-items: center;
  gap: var(--m-gap-sm);
  padding: var(--m-gap-sm) var(--m-gap-md);
  min-height: var(--m-touch-min);
  border-bottom: 0.5px solid rgba(0, 0, 0, 0.04);
}

.m-list-item:last-child {
  border-bottom: none;
}

.m-list-item.clickable {
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.m-list-item.clickable:active {
  background: rgba(0, 0, 0, 0.04);
}

.m-list-item.active {
  background: var(--m-accent-glow);
}

.m-list-item-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.m-list-item-body {
  flex: 1;
  min-width: 0;
}

.m-list-item-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--m-text-primary);
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.m-list-item-subtitle {
  font-size: 13px;
  color: var(--m-text-secondary);
  line-height: 1.3;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.m-list-item-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--m-text-primary);
  text-align: right;
  flex-shrink: 0;
}

.m-list-item-accessory {
  flex-shrink: 0;
}

.m-list-item-chevron {
  color: var(--m-text-tertiary);
  flex-shrink: 0;
}
</style>

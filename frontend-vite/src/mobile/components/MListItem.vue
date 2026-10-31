<template>
  <!-- 可点击项必须是键盘可达的（A-M39）：移动端组件同样要能被外接键盘/辅助技术操作 -->
  <div
    :class="['m-list-item', { clickable: interactive, active }]"
    :role="interactive ? 'button' : undefined"
    :tabindex="interactive ? 0 : undefined"
    @click="handleClick"
    @keydown="onKeydown"
  >
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
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{
  title: string
  subtitle?: string
  to?: string
  active?: boolean
  /** 有动作但非跳转的项（如"退出登录"）：显式声明可点击样式，配合外部原生 @click 使用。 */
  clickable?: boolean
}>()

const router = useRouter()

/** 可交互 = 有跳转目标，或调用方显式声明 clickable（如「退出登录」） */
const interactive = computed(() => props.clickable === true || !!props.to)

function handleClick() {
  if (props.to) {
    router.push(props.to)
  }
}

/**
 * Enter / Space 触发一次真实 click。
 * 用 `.click()` 而不是直接 router.push：clickable 项的真正动作来自调用方的原生
 * @click（外部监听），只有派发原生事件才能让它和鼠标路径走同一条代码。
 */
function onKeydown(e: KeyboardEvent) {
  if (!interactive.value) return
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault() // Space 默认会滚动页面
    ;(e.currentTarget as HTMLElement).click()
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

/* 键盘焦点必须可见（A-M39）：移动端组件在桌面/外接键盘下同样要能定位当前项 */
.m-list-item.clickable:focus-visible {
  outline: 2px solid var(--m-accent, #2563eb);
  outline-offset: -2px;
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

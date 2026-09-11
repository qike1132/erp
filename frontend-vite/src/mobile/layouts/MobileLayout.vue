<template>
  <div class="m-layout">
    <MobileNotificationBell v-if="authStore.isLoggedIn" />
    <div class="m-layout-content">
      <router-view />
    </div>
    <MobileTabBar :tabs="tabs" @tab-click="handleTabAction" />
    <MobileSubPage :visible="subPageVisible" @closed="subPageVisible = false">
      <router-view name="sub" />
    </MobileSubPage>
    <div v-if="quickActionsVisible" class="m-quick-overlay" @click="quickActionsVisible = false">
      <div class="m-quick-sheet" @click.stop>
        <h3 class="m-quick-title">快捷操作</h3>
        <div class="m-quick-grid">
          <button
            v-for="action in quickActions"
            :key="action.name"
            class="m-quick-item"
            @click="handleQuickAction(action)"
          >
            <div class="m-quick-icon" :style="{ background: action.color }">
              <component :is="action.icon" />
            </div>
            <span class="m-quick-label">{{ action.label }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, defineComponent, markRaw, type Component } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import MobileTabBar from './components/MobileTabBar.vue'
import MobileSubPage from './components/MobileSubPage.vue'
import MobileNotificationBell from './components/MobileNotificationBell.vue'

const router = useRouter()
const authStore = useAuthStore()
const subPageVisible = ref(false)
const quickActionsVisible = ref(false)

/**
 * 将 SVG 字符串转换为 Vue 组件（运行时渲染，无需模板编译器）。
 * 解析 SVG 根元素的属性并通过 h() 渲染，内部子元素使用 innerHTML 设置。
 */
// 安全说明：所有 SVG 字符串均来自下方 _tabDefs / _quickDefs / _quickSvg 等模块级常量，
// 非用户输入，XSS 风险极低。sanitizeSvgInner 作为防御性校验，拒绝脚本/事件处理器等危险内容。
function sanitizeSvgInner(html: string): string {
  if (/<script|on\w+\s*=|javascript:|<iframe|<object|<embed/i.test(html)) {
    throw new Error('[MobileLayout] SVG inner content contains disallowed markup')
  }
  return html
}

function createSvgIcon(svgString: string): Component {
  const m = svgString.match(/^<svg([^>]*)>([\s\S]*)<\/svg>$/)
  if (!m) throw new Error('Invalid SVG: ' + svgString.slice(0, 50))
  const attrStr = m[1] ?? ''
  const innerHtml = sanitizeSvgInner(m[2] ?? '')
  const attrs: Record<string, string> = {}
  for (const am of attrStr.matchAll(/([\w-]+)="([^"]*)"/g)) {
    if (am[1]) attrs[am[1]] = am[2] ?? ''
  }
  return markRaw(defineComponent({
    render() {
      // innerHTML 内容经 sanitizeSvgInner 校验且源自模块级 SVG 常量，等价于 v-html 的安全用法
      return h('svg', { ...attrs, innerHTML: innerHtml })
    }
  }))
}

// 响应式路由：移动端路径已统一在根级别，无需前缀
interface TabDef { name: string; label: string; path: string; template: string }

const _tabDefs: TabDef[] = [
  { name: 'overview', label: '概览', path: '/dashboard', template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>` },
  { name: 'shipment', label: '出货', path: '/shipment', template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>` },
  { name: 'orders', label: '订单', path: '/customer-order', template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>` },
  { name: 'profile', label: '我的', path: '/profile', template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>` },
]

const _quickSvg = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`

const _tabToItem = (t: TabDef) => ({ name: t.name, label: t.label, to: t.path, icon: createSvgIcon(t.template) })

const tabs = computed(() => [
  ..._tabDefs.slice(0, 2).map(_tabToItem),
  { name: 'quick', label: '快捷', center: true, icon: createSvgIcon(_quickSvg) },
  ..._tabDefs.slice(2).map(_tabToItem),
])

interface QuickAction {
  name: string
  label: string
  icon: Component
  color: string
  to: string
}

const _quickDefs = [
  { name: 'purchase', label: '采购中心', path: '/purchase', color: '#0071E3', template: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><line x1="3" y1="6" x2="21" y2="6"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>` },
  { name: 'material-calc', label: '物料计算', path: '/material-calculator', color: '#30D158', template: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="8" y1="10" x2="16" y2="10"/><line x1="8" y1="14" x2="12" y2="14"/></svg>` },
  { name: 'incoming', label: '来料登记', path: '/incoming', color: '#FF9500', template: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>` },
  { name: 'production', label: '生产报表', path: '/production', color: '#AF52DE', template: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>` },
  { name: 'batch', label: '批次号查询', path: '/batch', color: '#FF2D55', template: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>` },
  { name: 'case', label: '皮套管理', path: '/case', color: '#5AC8FA', template: `<svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>` },
]

const quickActions = computed<QuickAction[]>(() =>
  _quickDefs.map((d) => ({
    name: d.name,
    label: d.label,
    color: d.color,
    to: d.path,
    icon: createSvgIcon(d.template),
  })),
)

function handleTabAction(name: string) {
  if (name === 'quick') {
    quickActionsVisible.value = !quickActionsVisible.value
  }
}

function handleQuickAction(action: QuickAction) {
  quickActionsVisible.value = false
  router.push(action.to)
}
</script>

<style scoped>
.m-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--m-bg-deep);
}

.m-layout-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.m-quick-overlay {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: flex-end;
  animation: m-fade-in 0.2s var(--m-ease-smooth);
}

@keyframes m-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.m-quick-sheet {
  width: 100%;
  background: var(--m-bg-surface);
  border-radius: 20px 20px 0 0;
  padding: 24px 16px calc(24px + var(--m-safe-bottom));
  box-shadow: var(--m-shadow-sheet);
  animation: m-sheet-up 0.35s var(--m-ease-spring);
}

@keyframes m-sheet-up {
  from { transform: translateY(100%); }
  to { transform: translateY(0); }
}

.m-quick-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--m-text-primary);
  margin: 0 0 16px;
}

.m-quick-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.m-quick-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 8px;
  border: none;
  background: none;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.m-quick-item:active {
  opacity: 0.6;
  transform: scale(0.92);
}

.m-quick-icon {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.m-quick-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--m-text-secondary);
  text-align: center;
  line-height: 1.2;
}
</style>

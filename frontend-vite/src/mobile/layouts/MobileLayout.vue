<template>
  <div class="m-layout">
    <div class="m-layout-content">
      <router-view />
    </div>
    <MobileTabBar :tabs="tabs" />
  </div>
</template>

<script setup lang="ts">
import { h, defineComponent, markRaw, type Component } from 'vue'
import MobileTabBar from './components/MobileTabBar.vue'

/**
 * 将 SVG 字符串转换为 Vue 组件（运行时渲染，无需模板编译器）。
 * 解析 SVG 根元素的属性并通过 h() 渲染，内部子元素使用 innerHTML 设置。
 */
// 安全说明：所有 SVG 字符串均来自下方 _tabDefs 模块级常量，非用户输入，
// XSS 风险极低。sanitizeSvgInner 作为防御性校验，拒绝脚本/事件处理器等危险内容。
function sanitizeSvgInner(html: string): string {
  if (/<script|on\w+\s*=|javascript:|<iframe|<object|<embed/i.test(html)) {
    throw new Error('[MobileLayout] SVG inner content contains disallowed markup')
  }
  return html
}

// 根 <svg> 属性白名单：仅放行无害展示属性；on* 事件句柄、href/xlink 等一律丢弃
const _SVG_ATTR_ALLOW = new Set([
  'viewBox', 'fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
  'class', 'width', 'height', 'xmlns', 'aria-hidden', 'role', 'focusable',
])

function createSvgIcon(svgString: string): Component {
  const m = svgString.match(/^<svg([^>]*)>([\s\S]*)<\/svg>$/)
  if (!m) throw new Error('Invalid SVG: ' + svgString.slice(0, 50))
  const attrStr = m[1] ?? ''
  const innerHtml = sanitizeSvgInner(m[2] ?? '')
  const attrs: Record<string, string> = {}
  for (const am of attrStr.matchAll(/([\w-]+)="([^"]*)"/g)) {
    const name = am[1] ?? ''
    const value = am[2] ?? ''
    if (!_SVG_ATTR_ALLOW.has(name)) continue // 白名单外属性（含 on\w+ 事件）直接丢弃
    if (/javascript:/i.test(value)) continue
    attrs[name] = value
  }
  return markRaw(defineComponent({
    render() {
      // innerHTML 内容经 sanitizeSvgInner 校验且源自模块级 SVG 常量，等价于 v-html 的安全用法；
      // 根属性已过 _SVG_ATTR_ALLOW 白名单
      return h('svg', { ...attrs, innerHTML: innerHtml })
    }
  }))
}

// 2026-11-23：移动端只保留「概览 / 我的」两个 tab（登录不在 tab 内）。
// 原「出货 / 订单」tab、快捷面板与通知铃铛随对应页面下线一并移除。
interface TabDef { name: string; label: string; path: string; template: string }

const _tabDefs: TabDef[] = [
  { name: 'overview', label: '概览', path: '/dashboard', template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>` },
  { name: 'profile', label: '我的', path: '/profile', template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>` },
]

const tabs = _tabDefs.map((t) => ({ name: t.name, label: t.label, to: t.path, icon: createSvgIcon(t.template) }))
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
</style>
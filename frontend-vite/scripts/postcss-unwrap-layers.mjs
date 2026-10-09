/**
 * postcss-unwrap-layers.mjs — 把 Tailwind v4 产物里的 `@layer` **原地解包**成普通 CSS。
 *
 * 为什么需要它
 * ---------------------------------------------------------------------------
 * Tailwind v4 的产物把一切包在 `@layer theme/base/components/utilities/properties` 里。
 * 旧内核（Chrome < 99）不认识 `@layer` 这个 at-rule，会**整块跳过**（未知 at-rule 连同
 * 内容一起忽略）——于是整张样式表被丢弃，页面退化成无样式。这正是"旧内核布局错乱/
 * 样式丢失"的 CSS 侧根因。
 *
 * 为什么是"原地解包"而不是用 @csstools/postcss-cascade-layers
 * ---------------------------------------------------------------------------
 * 实测：构建产物里 5 个 `@layer` 块**本就连续且排在最前**，所有无层规则都在其后。
 * 因此只需按源码顺序解包，级联语义即与原来**完全一致**：
 *   层间顺序(theme<base<components<utilities) 由块的出现顺序表达；
 *   "无层规则胜过分层规则"由「无层规则在后」表达。
 * 而 csstools 那个插件为通用性会给**每个选择器**加 `:not(#\#)` 特异性 hack（实测产物
 * 膨胀 +40%、全局特异性被改写），本项目用不上、也不想要。
 *
 * 注：`@layer a, b, c;` 这种「只声明顺序」的语句解包后无意义，直接丢弃。
 */
export const unwrapCascadeLayers = {
  postcssPlugin: 'unwrap-cascade-layers',
  AtRule: {
    layer(atRule) {
      if (!atRule.nodes) {
        atRule.remove() // `@layer a, b, c;` 顺序声明 → 丢弃
        return
      }
      atRule.replaceWith(...atRule.nodes) // `@layer x { ... }` → 原地解包
    },
  },
}

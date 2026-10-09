import { unwrapCascadeLayers } from './scripts/postcss-unwrap-layers.mjs'
import oklabFunction from '@csstools/postcss-oklab-function'

// 旧内核（较老的 Chromium）CSS 降级层。两件事：
// 1) 解包 `@layer` —— Tailwind v4 产物全部包在层里，Chrome<99 不认 `@layer` 会整块跳过
//    → 整张样式表被丢弃（这是"布局错乱/样式丢失"的根因）。见插件文件头。
// 2) `oklch()` → rgb —— Tailwind 默认调色板用 oklch 定义变量（本项目用到 gray-*/amber-500），
//    Chrome<111 不认。**必须 preserve:false（直接替换）**：这些是自定义属性，同名的后一条
//    声明总是胜出，若保留 oklch 兜底会被它盖掉，旧内核拿到的仍是无值。
// 注：`color-mix()` 无需处理 —— 产物里它都在 `@supports (color:color-mix(...))` 守卫内、
//     且每条都有普通 hex 兜底，旧内核跳过守卫即用兜底。
// 依赖 @tailwindcss/vite 的 `enforce:'pre'`（先展开再轮到本 PostCSS）。构建后由
// scripts/check-css-legacy.mjs 自检产物已无 `@layer`，防插件顺序变化导致静默回归。
export default {
  plugins: [unwrapCascadeLayers, oklabFunction({ preserve: false })],
}

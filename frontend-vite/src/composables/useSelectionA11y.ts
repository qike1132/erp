/**
 * 选中态无障碍范式（唯一入口）
 *
 * 背景：`/pattern-room` 审查（A11Y-06/07）发现版师列表、状态筛选胶囊、版本 chip
 * 三方各自用 `:class="{ active: ... }"` 表达选中，读屏器完全感知不到当前选择。
 * 全站凡「一组互斥选项」都走本文件，不要各自手写 `aria-pressed` 字面量。
 *
 * 两个范式，语义不同，别混用：
 *   1. 切换按钮组（本文件）—— 选项仍在同一视图内，用 `aria-pressed` 表达「按下/未按下」。
 *      适用：筛选胶囊、版师列表、版本 chip。
 *   2. 真正的 tab 切换 —— 用 `components/ui/UiTabs.vue`（内部是 reka-ui TabsRoot，
 *      自带 role="tablist"/"tab"/"tabpanel"、aria-selected 与 ←/→ 方向键）。
 *      适用：切换下方面板内容的角色页签、订单页签。
 *
 * 为什么必须返回字符串而不是 boolean：
 *   `aria-pressed` 的「属性不存在」与「值为 false」是两种不同语义 ——
 *   前者表示「这不是切换按钮」，后者表示「是切换按钮，当前未按下」。
 *   Vue 对 aria-* 属性虽会把 false 序列化成 "false"，但显式字符串可杜绝
 *   `v-bind` 合并、`attrs` 透传、SSR 水合任一环节把它吃成缺省。
 */

import { toValue, type MaybeRefOrGetter } from 'vue'

/** aria-pressed 的合法取值；缺省（属性不存在）不在此列，见文件头说明 */
export type AriaPressedValue = 'true' | 'false' | 'mixed'

/** 可透传到选项元素上的无障碍属性 */
export interface SelectionItemAttrs {
  'aria-pressed': AriaPressedValue
}

/**
 * 生成单个选项的 aria-pressed 属性。
 * 纯函数，便于在不依赖组件实例的地方（如渲染函数、测试）复用。
 */
export function selectionItemAttrs(isActive: boolean): SelectionItemAttrs {
  return { 'aria-pressed': isActive ? 'true' : 'false' }
}

/**
 * 互斥选项组的选中态辅助。
 *
 * @param activeValue 当前选中的值（响应式：ref / getter / 普通值均可）
 * @param equals      比较函数。默认 `===`；值为对象或需要按 id 比较时传入
 *
 * @example
 * const { itemAttrs } = useSelectionA11y(() => props.statusFilter)
 * <button v-for="opt in OPTIONS" :key="opt.value" v-bind="itemAttrs(opt.value)">
 */
export function useSelectionA11y<T>(
  activeValue: MaybeRefOrGetter<T | null | undefined>,
  equals: (active: T | null | undefined, candidate: T) => boolean = (active, candidate) =>
    active === candidate,
) {
  /** 某选项是否处于选中态 */
  function isActive(candidate: T): boolean {
    return equals(toValue(activeValue), candidate)
  }

  /**
   * 选项要展开到元素上的属性。
   * 注意：只能用在 `<button>`（或 role="button" 的元素）上；用在普通 div 上会让
   * 读屏器读出「切换按钮」语义却没有键盘行为，反而更糟。
   */
  function itemAttrs(candidate: T): SelectionItemAttrs {
    return selectionItemAttrs(isActive(candidate))
  }

  return { isActive, itemAttrs }
}

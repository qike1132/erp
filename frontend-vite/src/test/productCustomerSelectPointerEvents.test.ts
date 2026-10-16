/**
 * ProductCustomerSelect 面板在模态弹窗（UiDialog）内必须可交互 —— OCR review 2026-10-16 的 High。
 *
 * reka-ui 的 DismissableLayer 在模态打开时把 document.body 设为 pointer-events:none
 * （见 components/ui/UiDialog.vue 用的 DialogContent）。面板经 Teleport 挂到 body
 * （`.pcs-panel` 是 body 的兄弟、position:fixed），会继承 none → 选项渲染出来但点不动。
 * 面板显式声明 `pointer-events: auto` 恢复本子树可交互。
 *
 * 源码级断言（参照 zLayers.test.ts 的写法）：删掉这条声明即变红，锁死回归。
 */
import { describe, expect, it } from 'vitest'
import { cssRule, readSfc } from './support/cssRule'

describe('ProductCustomerSelect 面板 pointer-events 契约', () => {
  const src = readSfc('src/views/product/components/ProductCustomerSelect.vue')

  it('.pcs-panel 显式声明 pointer-events:auto（模态弹窗打开时 body 被设为 none）', () => {
    expect(cssRule(src, '.pcs-panel')).toContainEqual(['pointer-events', 'auto'])
  })
})

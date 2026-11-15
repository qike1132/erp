/**
 * 打印层转义工具回归（2026-11-15 评审 A3）。
 *
 * 背景：`escapeHtml` 原先签名是 `(str: string)` 且直接 `.replace` —— 后端某字段为空时
 * 打印/导出会在拼字符串阶段抛 TypeError，界面表现为「点按钮毫无反应」，而屏幕（有 `|| ''`）
 * 完全正常。信号是「屏幕正常、打印死掉」，最难查。故空值必须转成空串。
 */
import { describe, it, expect } from 'vitest'
import { escapeHtml } from '@/utils/print'

describe('escapeHtml 容忍空值与非法输入', () => {
  it('null / undefined → 空串（不抛异常）', () => {
    expect(escapeHtml(null)).toBe('')
    expect(escapeHtml(undefined)).toBe('')
  })

  it('数字 / 布尔 / 0 按原义转字符串（0 不得丢失）', () => {
    expect(escapeHtml(0)).toBe('0')
    expect(escapeHtml(12.5)).toBe('12.5')
    expect(escapeHtml(false)).toBe('false')
  })

  it('字符串转义口径不变（& < > "，单引号保留）', () => {
    expect(escapeHtml('a&b<c>d"e\'f')).toBe('a&amp;b&lt;c&gt;d&quot;e\'f')
  })
})

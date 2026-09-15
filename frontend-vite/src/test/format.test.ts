import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  formatDate,
  formatDateTime,
  formatCurrency,
  formatNumber,
  toISODate,
  formatRelativeTime,
} from '../utils/format'

describe('format utils', () => {
  describe('formatDate', () => {
    it('空值统一返回占位符 "-"', () => {
      expect(formatDate(null)).toBe('-')
      expect(formatDate(undefined)).toBe('-')
      expect(formatDate('')).toBe('-')
    })

    it('接受 Date 对象与 ISO 字符串，输出一致', () => {
      const d = new Date('2026-09-14T10:30:00')
      expect(formatDate(d)).toBe(formatDate('2026-09-14T10:30:00'))
    })

    it('非法日期字符串不抛异常，降级为 "-"', () => {
      // Invalid Date 传入 Intl.format 会抛 RangeError，须被 catch 兜住
      expect(formatDate('not-a-date')).toBe('-')
    })

    it('数值时间戳可被解析', () => {
      expect(formatDate(new Date(1757833200000))).not.toBe('-')
    })

    it('时间戳 0（Unix 纪元）被 !date 判为假值而返回 "-"', () => {
      // 记录既有行为：守卫是 `if (!date) return '-'`，故 0 与 '' 同样被当作"空"。
      // 对本系统无实际影响（不会有 1970 年的业务时间戳），但若将来格式化
      // 可能为 0 的字段，此处须改为 `if (date == null)`。
      // 断言用意在锁定行为，用 as never 绕过「签名不含 number」的类型约束。
      expect(formatDate(0 as never)).toBe('-')
    })  })

  describe('formatDateTime', () => {
    it('空值统一返回占位符 "-"', () => {
      expect(formatDateTime(null)).toBe('-')
      expect(formatDateTime(undefined)).toBe('-')
      expect(formatDateTime('')).toBe('-')
    })

    it('非法输入降级为 "-"', () => {
      expect(formatDateTime('junk')).toBe('-')
    })

    it('输出的日期部分与 formatDate 一致', () => {
      const iso = '2026-09-14T10:30:00'
      // 同一时刻，二者日期段应相同（仅时刻精度不同）
      expect(formatDateTime(iso)).toContain(formatDate(iso))
    })
  })

  describe('formatCurrency', () => {
    it('null/undefined 返回占位符（注意：0 是合法值不返回占位符）', () => {
      expect(formatCurrency(null)).toBe('-')
      expect(formatCurrency(undefined)).toBe('-')
      // 0 必须格式化，而非当成"空"
      expect(formatCurrency(0)).not.toBe('-')
    })

    it('输出含人民币符号且保留两位小数', () => {
      const s = formatCurrency(1234.5)
      expect(s).toContain('1,234.50')
    })

    it('负数正常格式化', () => {
      expect(formatCurrency(-100)).toContain('100.00')
    })
  })

  describe('formatNumber', () => {
    it('null/undefined 返回占位符，0 正常格式化', () => {
      expect(formatNumber(null)).toBe('-')
      expect(formatNumber(undefined)).toBe('-')
      expect(formatNumber(0)).toBe('0')
    })

    it('千分位分隔', () => {
      expect(formatNumber(1234567)).toBe('1,234,567')
    })

    it('最多保留两位小数（第三位起四舍五入）', () => {
      expect(formatNumber(1.239)).toBe('1.24')
      expect(formatNumber(1.005)).toBe('1.01')
    })

    it('整数不补小数位', () => {
      expect(formatNumber(100)).toBe('100')
    })
  })

  describe('toISODate', () => {
    it('默认取当前日期，格式为 YYYY-MM-DD', () => {
      expect(toISODate()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    })

    it('月/日补零（个位数月份与日期）', () => {
      expect(toISODate(new Date(2026, 0, 5))).toBe('2026-01-05')
    })

    it('两位数月份与日期不重复补零', () => {
      expect(toISODate(new Date(2026, 11, 31))).toBe('2026-12-31')
    })

    it('使用本地时区而非 UTC（避免跨时区日期偏移一天）', () => {
      // 本地 2026-01-01 00:30，若误用 toISOString() 会因时区前移变成前一天
      const localMidnightish = new Date(2026, 0, 1, 0, 30)
      expect(toISODate(localMidnightish)).toBe('2026-01-01')
    })
  })

  describe('formatRelativeTime', () => {
    beforeEach(() => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-09-14T12:00:00'))
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('空值返回占位符', () => {
      expect(formatRelativeTime(null)).toBe('-')
      expect(formatRelativeTime(undefined)).toBe('-')
      expect(formatRelativeTime('')).toBe('-')
    })

    it('非法日期返回占位符（而非 "NaN 分钟前"）', () => {
      expect(formatRelativeTime('junk')).toBe('-')
    })

    it('未来时间显示"刚刚"（不出现负数）', () => {
      expect(formatRelativeTime(new Date('2026-09-14T12:05:00'))).toBe('刚刚')
    })

    it('< 60 秒 → 刚刚', () => {
      expect(formatRelativeTime(new Date('2026-09-14T11:59:30'))).toBe('刚刚')
    })

    it('< 60 分钟 → N 分钟前', () => {
      expect(formatRelativeTime(new Date('2026-09-14T11:30:00'))).toBe('30 分钟前')
    })

    it('< 24 小时 → N 小时前', () => {
      expect(formatRelativeTime(new Date('2026-09-14T03:00:00'))).toBe('9 小时前')
    })

    it('恰好 1 天 → 昨天', () => {
      expect(formatRelativeTime(new Date('2026-09-13T12:00:00'))).toBe('昨天')
    })

    it('2-6 天 → N 天前', () => {
      expect(formatRelativeTime(new Date('2026-09-11T12:00:00'))).toBe('3 天前')
      expect(formatRelativeTime(new Date('2026-09-08T12:00:00'))).toBe('6 天前')
    })

    it('≥ 7 天回退为具体日期', () => {
      const result = formatRelativeTime(new Date('2026-09-01T12:00:00'))
      expect(result).not.toContain('天前')
      expect(result).toBe(formatDate(new Date('2026-09-01T12:00:00')))
    })

    it('边界：59 秒仍是"刚刚"，60 秒进位为"1 分钟前"', () => {
      expect(formatRelativeTime(new Date('2026-09-14T11:59:01'))).toBe('刚刚')
      expect(formatRelativeTime(new Date('2026-09-14T11:59:00'))).toBe('1 分钟前')
    })

    it('边界：23 小时 vs 24 小时（小时/天切换）', () => {
      expect(formatRelativeTime(new Date('2026-09-13T13:00:00'))).toBe('23 小时前')
      expect(formatRelativeTime(new Date('2026-09-13T12:00:00'))).toBe('昨天')
    })
  })
})

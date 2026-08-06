const dateFormatter = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
const currencyFormatter = new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', minimumFractionDigits: 2 })
const numberFormatter = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })

export function formatDate(date: string | Date | null | undefined): string {
  if (!date) return '-'
  try {
    return dateFormatter.format(new Date(date))
  } catch {
    return '-'
  }
}

export function formatDateTime(date: string | Date | null | undefined): string {
  if (!date) return '-'
  try {
    return dateTimeFormatter.format(new Date(date))
  } catch {
    return '-'
  }
}

export function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '-'
  return currencyFormatter.format(value)
}

export function formatNumber(value: number | null | undefined): string {
  if (value == null) return '-'
  return numberFormatter.format(value)
}

export function toISODate(date: Date = new Date()): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/**
 * 相对时间格式化：刚刚 / N 分钟前 / N 小时前 / 昨天 / N 天前 / 具体日期
 * 仅用于通知列表等轻量展示场景，不引入额外依赖。
 */
export function formatRelativeTime(date: string | Date | null | undefined): string {
  if (!date) return '-'
  let d: Date
  try {
    d = new Date(date)
  } catch {
    return '-'
  }
  if (isNaN(d.getTime())) return '-'

  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 0) return '刚刚'

  const sec = Math.floor(diff / 1000)
  if (sec < 60) return '刚刚'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day === 1) return '昨天'
  if (day < 7) return `${day} 天前`
  // 超过 7 天回退到具体日期
  return formatDate(d)
}

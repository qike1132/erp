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

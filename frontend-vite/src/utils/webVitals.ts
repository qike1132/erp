import { onLCP, onCLS, onINP, onTTFB } from 'web-vitals'

interface VitalMetric {
  name: string
  value: number
  rating: string
  delta: number
  navigationType: string
  timestamp: number
}

const queue: VitalMetric[] = []
const history: VitalMetric[] = []
let flushTimer: ReturnType<typeof setTimeout> | null = null
let initialized = false

function reportMetrics(batch: VitalMetric[]) {
  if (batch.length === 0 || typeof navigator === 'undefined' || !navigator.sendBeacon) return

  const payload = JSON.stringify({ vitals: batch })
  try {
    navigator.sendBeacon('/api/v1/monitoring/vitals', new Blob([payload], { type: 'application/json' }))
  } catch {
    // sendBeacon 失败时静默丢弃，避免影响业务
  }
}

function flushMetrics() {
  if (queue.length === 0) return
  const batch = queue.splice(0, queue.length)
  history.push(...batch)
  if (history.length > 100) history.splice(0, history.length - 100)

  reportMetrics(batch)
}

function handleVital(metric: { name: string; value: number; rating: string; delta: number; navigationType?: string }) {
  queue.push({
    name: metric.name,
    value: metric.value,
    rating: metric.rating,
    delta: metric.delta,
    navigationType: metric.navigationType ?? 'unknown',
    timestamp: Date.now(),
  })
  if (queue.length > 50) queue.shift()

  if (flushTimer) clearTimeout(flushTimer)
  flushTimer = setTimeout(flushMetrics, 5000)

  if (metric.rating === 'poor') {
    console.warn(`[WebVitals] ${metric.name}: ${metric.value.toFixed(1)}ms (${metric.rating})`)
  }
}

export function initWebVitals() {
  if (initialized) return
  initialized = true
  onLCP(handleVital)
  onCLS(handleVital)
  onINP(handleVital)
  onTTFB(handleVital)

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushMetrics()
  })
}

export function getVitalsSummary(): Record<string, { value: number; rating: string }> {
  const summary: Record<string, { value: number; rating: string }> = {}
  for (const m of history) {
    const cur = summary[m.name]
    if (!cur || m.value > cur.value) {
      summary[m.name] = { value: m.value, rating: m.rating }
    }
  }
  return summary
}

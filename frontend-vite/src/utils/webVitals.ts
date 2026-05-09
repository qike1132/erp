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

function flushMetrics() {
  if (queue.length === 0) return
  const batch = queue.splice(0, queue.length)
  history.push(...batch)
  if (history.length > 100) history.splice(0, history.length - 100)

  const body = JSON.stringify({ vitals: batch })
  fetch('/api/v1/monitoring/vitals', {
    method: 'POST',
    body,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    keepalive: true,
  }).catch(() => {})
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

  if (flushTimer) clearTimeout(flushTimer)
  flushTimer = setTimeout(flushMetrics, 5000)

  if (metric.rating === 'poor') {
    console.warn(`[WebVitals] ${metric.name}: ${metric.value.toFixed(1)}ms (${metric.rating})`)
  }
}

export function initWebVitals() {
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
    if (!summary[m.name] || m.value > summary[m.name].value) {
      summary[m.name] = { value: m.value, rating: m.rating }
    }
  }
  return summary
}

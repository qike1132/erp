import { onMounted, onUnmounted } from 'vue'
import { devLog, devGroup, devGroupEnd } from '@/utils/devLog'

interface PerfEntry {
  name: string
  duration: number
  timestamp: number
}

const entries: PerfEntry[] = []
const isDev = import.meta.env?.DEV

function mark(name: string) {
  if (!isDev) return
  performance.mark(name)
}

function measure(name: string, startMark: string, endMark?: string) {
  if (!isDev) return
  const end = endMark ?? `${name}-end`
  if (!endMark) performance.mark(end)
  try {
    performance.measure(name, startMark, end)
    const [entry] = performance.getEntriesByName(name, 'measure').slice(-1)
    if (entry) {
      const record: PerfEntry = { name, duration: Math.round(entry.duration * 100) / 100, timestamp: Date.now() }
      entries.push(record)
      const status = entry.duration < 500 ? '✓' : entry.duration < 1000 ? '⚠' : '✗'
      devLog(`[Perf] ${status} ${name}: ${entry.duration.toFixed(1)}ms`)
    }
  } catch {
    console.warn(`[Perf] measure failed: ${name}`)
  }
}

function markEnd(name: string) {
  if (!isDev) return
  performance.mark(`${name}-end`)
}

function getEntries(): PerfEntry[] {
  return [...entries]
}

function getSummary(): Record<string, { avg: number; min: number; max: number; count: number }> {
  const groups: Record<string, number[]> = {}
  for (const e of entries) {
    ;(groups[e.name] ??= []).push(e.duration)
  }
  const summary: Record<string, { avg: number; min: number; max: number; count: number }> = {}
  for (const [name, durations] of Object.entries(groups)) {
    summary[name] = {
      avg: Math.round((durations.reduce((a, b) => a + b, 0) / durations.length) * 100) / 100,
      min: Math.round(Math.min(...durations) * 100) / 100,
      max: Math.round(Math.max(...durations) * 100) / 100,
      count: durations.length,
    }
  }
  return summary
}

function clear() {
  entries.length = 0
}

export function usePerfMark(prefix: string) {
  const p = (name: string) => `${prefix}:${name}`

  onMounted(() => {
    mark(p('mount'))
  })

  onUnmounted(() => {
    if (isDev && entries.length > 0) {
      const pageEntries = entries.filter((e) => e.name.startsWith(prefix))
      if (pageEntries.length > 0) {
        devGroup(`[Perf Summary] ${prefix}`)
        for (const e of pageEntries) {
          const status = e.duration < 500 ? '✓' : e.duration < 1000 ? '⚠' : '✗'
          devLog(`  ${status} ${e.name}: ${e.duration.toFixed(1)}ms`)
        }
        devGroupEnd()
      }
    }
  })

  return {
    markMountEnd: () => { markEnd(p('mount')); measure(p('mount-time'), p('mount'), p('mount-end')) },
    mark: (name: string) => mark(p(name)),
    markEnd: (name: string) => markEnd(p(name)),
    measure: (name: string, start: string, end?: string) => measure(p(name), p(start), end ? p(end) : undefined),
    measureFromMount: (name: string) => measure(p(name), p('mount')),
  }
}

if (isDev) {
  ;(window as unknown as Record<string, unknown>).__erp_perf_marks__ = { getEntries, getSummary, clear }
  devLog('[Perf Marks] window.__erp_perf_marks__')
}

export { mark, markEnd, measure, getEntries, getSummary, clear }

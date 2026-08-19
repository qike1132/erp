/**
 * ERP 前端性能审计工具
 * DOM审计 / 重排重绘监测 / 事件监听器审计 / 长任务检测 / 内存快照
 * 开发模式挂载到 window.__erp_perf__
 */
import { devLog, devGroup, devGroupEnd } from '@/utils/devLog'

export interface DOMAuditResult {
  totalNodes: number
  depth: number
  heavyElements: { selector: string; count: number }[]
  timestamp: string
}

export function auditDOM(): DOMAuditResult {
  const result: DOMAuditResult = { totalNodes: 0, depth: 0, heavyElements: [], timestamp: new Date().toISOString() }
  function walk(node: Node, depth: number) {
    result.totalNodes++
    if (depth > result.depth) result.depth = depth
    for (const c of Array.from(node.childNodes)) walk(c, depth + 1)
  }
  walk(document.body, 1)
  const selectors = [
    ['table','table'], ['tr','tr'], ['.virtual-list-item','virtual-list-item'],
    ['select','select'], ['input','input'], ['img','img'],
  ] as const
  for (const [sel, label] of selectors) {
    const count = document.querySelectorAll(sel).length
    if (count > 0) result.heavyElements.push({ selector: label, count })
  }
  return result
}

export function monitorReflowRepaint(durationMs = 10000): void {
  let reflowCount = 0
  const orig = window.getComputedStyle
  window.getComputedStyle = function (elt: Element, pseudoElt?: string | null) { reflowCount++; return orig.call(window, elt, pseudoElt ?? null) }
  if ('PerformanceObserver' in window) {
    try {
      const obs = new PerformanceObserver((list) => { for (const e of list.getEntries()) if (!((e as { hadRecentInput?: boolean }).hadRecentInput)) reflowCount++ })
      obs.observe({ type: 'layout-shift', buffered: true })
    } catch {}
  }
  setTimeout(() => { window.getComputedStyle = orig; devLog(`[性能] 重排次数: ${reflowCount}`); if (reflowCount > 100) console.warn('[性能] 重排过多，建议用transform替代top/left') }, durationMs)
}

export function auditEventListeners(): { eventType: string; count: number }[] {
  const types = ['click','input','change','scroll','resize','keydown','mouseover','touchstart']
  const results: { eventType: string; count: number }[] = []
  for (const t of types) {
    let total = 0
    document.querySelectorAll('*').forEach((el) => { try { const l = (window as unknown as { getEventListeners?: (el: Element) => Record<string, Array<unknown>> }).getEventListeners?.(el); if (l?.[t]) total += l[t].length } catch {} })
    if (total > 0) { results.push({ eventType: t, count: total }); if (total > 50) console.warn(`[性能] ${t} 监听器过多: ${total}个，考虑事件委托`) }
  }
  return results
}

export function monitorLongTasks(durationMs = 30000): Promise<{ startTime: number; duration: number; name: string }[]> {
  const tasks: { startTime: number; duration: number; name: string }[] = []
  return new Promise((resolve) => {
    if (!('PerformanceObserver' in window)) { resolve([]); return }
    const obs = new PerformanceObserver((list) => { for (const e of list.getEntries()) { const t = { startTime: e.startTime, duration: e.duration, name: e.name }; tasks.push(t); if (e.duration > 100) console.warn(`[性能] 长任务: ${e.duration.toFixed(0)}ms`) } })
    try { obs.observe({ type: 'longtask', buffered: true }) } catch { obs.observe({ entryTypes: ['longtask'] }) }
    setTimeout(() => { obs.disconnect(); resolve(tasks) }, durationMs)
  })
}

export interface MemorySnapshot { timestamp: string; usedJSHeapSize: number; heapUtilization: number; domNodes: number }
export function takeMemorySnapshot(): MemorySnapshot | null {
  const m = (performance as unknown as { memory?: { usedJSHeapSize: number; totalJSHeapSize: number } }).memory
  if (!m) return null
  return { timestamp: new Date().toISOString(), usedJSHeapSize: m.usedJSHeapSize, heapUtilization: m.usedJSHeapSize / m.totalJSHeapSize, domNodes: document.querySelectorAll('*').length }
}

export async function runFullDiagnosis(): Promise<void> {
  devGroup('[ERP 性能诊断]')
  const dom = auditDOM()
  devLog(`DOM节点: ${dom.totalNodes}, 深度: ${dom.depth}`, dom.heavyElements)
  if (dom.totalNodes > 3000) console.warn(`DOM节点过多(${dom.totalNodes})，建议虚拟滚动`)
  const evt = auditEventListeners()
  for (const e of evt) devLog(`${e.eventType}: ${e.count}个监听器`)
  const mem = takeMemorySnapshot()
  if (mem) devLog(`堆: ${(mem.usedJSHeapSize/1024/1024).toFixed(1)}MB 利用率: ${(mem.heapUtilization*100).toFixed(1)}%`)
  const lt = await monitorLongTasks(5000)
  devLog(`长任务: ${lt.length}个`)
  devGroupEnd()
}

if (import.meta.env?.DEV) {
  ;(window as unknown as Record<string, unknown>).__erp_perf__ = { auditDOM, monitorReflowRepaint, auditEventListeners, monitorLongTasks, takeMemorySnapshot, runFullDiagnosis }
  devLog('[ERP性能工具] window.__erp_perf__')
}

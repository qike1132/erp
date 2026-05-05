/**
 * ERP 前端性能分析工具
 *
 * 功能：
 * 1. DOM 操作审计 - 统计 DOM 节点数、重排重绘频率
 * 2. 事件监听器监测 - 识别事件监听器过多、内存泄漏
 * 3. 长任务检测 - 识别阻塞主线程的操作
 * 4. 内存快照 - 追踪大对象和 GC 问题
 *
 * 使用方式：在浏览器控制台引入，或在 main.ts 中条件加载
 */

// ==================== DOM 审计 ====================

interface DOMAuditResult {
  totalNodes: number
  depth: number
  heavyElements: { selector: string; count: number }[]
  reflowCount: number
  repaintCount: number
  timestamp: string
}

export function auditDOM(): DOMAuditResult {
  const result: DOMAuditResult = {
    totalNodes: 0,
    depth: 0,
    heavyElements: [],
    reflowCount: 0,
    repaintCount: 0,
    timestamp: new Date().toISOString(),
  }

  // 统计总节点数和最大深度
  function walkDOM(node: Node, depth: number): void {
    result.totalNodes++
    if (depth > result.depth) result.depth = depth
    for (const child of Array.from(node.childNodes)) {
      walkDOM(child, depth + 1)
    }
  }
  walkDOM(document.body, 1)

  // 识别可能引起性能问题的重元素
  const heavySelectors = [
    { selector: 'table', label: 'table' },
    { selector: 'tr', label: 'tr' },
    { selector: '.virtual-list-item', label: 'virtual-list-item' },
    { selector: '[v-for]', label: 'v-for' },
    { selector: 'select', label: 'select' },
    { selector: 'input', label: 'input' },
    { selector: 'img', label: 'img' },
  ]
  for (const { selector, label } of heavySelectors) {
    const count = document.querySelectorAll(selector).length
    if (count > 0) {
      result.heavyElements.push({ selector: label, count })
    }
  }

  return result
}

// ==================== 重排/重绘监测 ====================

export function monitorReflowRepaint(durationMs: number = 10000): void {
  console.log(`[性能] 开始监测重排/重绘，持续 ${durationMs / 1000}s...`)

  let reflowCount = 0
  let repaintCount = 0

  // 劫持会触发重排的属性
  const reflowProperties = [
    'offsetTop', 'offsetLeft', 'offsetWidth', 'offsetHeight',
    'scrollTop', 'scrollLeft', 'scrollWidth', 'scrollHeight',
    'clientTop', 'clientLeft', 'clientWidth', 'clientHeight',
    'getBoundingClientRect', 'getComputedStyle',
  ]

  const originalGetComputedStyle = window.getComputedStyle
  window.getComputedStyle = function (...args: any[]) {
    reflowCount++
    return originalGetComputedStyle.apply(window, args as any)
  }

  // 使用 Performance Observer 监测布局偏移
  if ('PerformanceObserver' in window) {
    try {
      const layoutObserver = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if ((entry as any).hadRecentInput) continue
          reflowCount++
        }
      })
      layoutObserver.observe({ type: 'layout-shift', buffered: true })
    } catch {}

    try {
      const paintObserver = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (entry.entryType === 'paint') {
            repaintCount++
          }
        }
      })
      paintObserver.observe({ type: 'paint', buffered: true })
    } catch {}
  }

  setTimeout(() => {
    window.getComputedStyle = originalGetComputedStyle
    console.log(`[性能] 重排次数: ${reflowCount}, 重绘次数: ${repaintCount}`)
    if (reflowCount > 100) {
      console.warn(`[性能] 重排次数过多(${reflowCount})，建议使用 transform/opacity 替代 top/left 动画`)
    }
  }, durationMs)
}

// ==================== 事件监听器监测 ====================

interface EventListenerAudit {
  eventType: string
  count: number
  elements: { tag: string; id: string; listeners: number }[]
}

export function auditEventListeners(): EventListenerAudit[] {
  const eventTypes = ['click', 'input', 'change', 'scroll', 'resize', 'keydown', 'keyup', 'mouseover', 'mouseout', 'touchstart', 'touchmove']
  const results: EventListenerAudit[] = []

  for (const eventType of eventTypes) {
    const elements: EventListenerAudit['elements'] = []
    let totalCount = 0

    document.querySelectorAll('*').forEach((el) => {
      const listeners = getEventListeners(el as HTMLElement)
      const count = listeners[eventType]?.length || 0
      if (count > 0) {
        totalCount += count
        elements.push({
          tag: el.tagName.toLowerCase(),
          id: el.id || `(class: ${el.className?.toString().slice(0, 30) || 'none'})`,
          listeners: count,
        })
      }
    })

    if (totalCount > 0) {
      results.push({ eventType, count: totalCount, elements: elements.slice(0, 10) })
    }
  }

  // 警告阈值
  for (const r of results) {
    if (r.count > 50) {
      console.warn(`[性能] ${r.eventType} 事件监听器过多: ${r.count} 个，考虑使用事件委托`)
    }
  }

  return results
}

// ==================== 长任务监测 ====================

interface LongTaskInfo {
  startTime: number
  duration: number
  name: string
  attribution: string
}

export function monitorLongTasks(durationMs: number = 30000): Promise<LongTaskInfo[]> {
  const tasks: LongTaskInfo[] = []

  return new Promise((resolve) => {
    if (!('PerformanceObserver' in window)) {
      console.warn('[性能] PerformanceObserver 不可用，无法监测长任务')
      resolve([])
      return
    }

    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const task: LongTaskInfo = {
          startTime: entry.startTime,
          duration: entry.duration,
          name: entry.name,
          attribution: (entry as any).attribution?.[0]?.name || 'unknown',
        }
        tasks.push(task)
        if (entry.duration > 100) {
          console.warn(
            `[性能] 长任务检测: ${entry.duration.toFixed(0)}ms (${task.attribution})`,
          )
        }
      }
    })

    try {
      observer.observe({ type: 'longtask', buffered: true })
    } catch {
      observer.observe({ entryTypes: ['longtask'] })
    }

    setTimeout(() => {
      observer.disconnect()
      console.log(`[性能] 长任务监测完成，共检测到 ${tasks.length} 个长任务`)
      resolve(tasks)
    }, durationMs)
  })
}

// ==================== 内存监测 ====================

interface MemorySnapshot {
  timestamp: string
  usedJSHeapSize: number
  totalJSHeapSize: number
  jsHeapSizeLimit: number
  heapUtilization: number
  domNodes: number
  detachedNodes: number
}

export function takeMemorySnapshot(): MemorySnapshot | null {
  const performance = window.performance as any
  if (!performance?.memory) {
    console.warn('[性能] performance.memory 不可用(需Chrome --enable-precise-memory-info)')
    return null
  }

  const mem = performance.memory
  const snapshot: MemorySnapshot = {
    timestamp: new Date().toISOString(),
    usedJSHeapSize: mem.usedJSHeapSize,
    totalJSHeapSize: mem.totalJSHeapSize,
    jsHeapSizeLimit: mem.jsHeapSizeLimit,
    heapUtilization: mem.usedJSHeapSize / mem.totalJSHeapSize,
    domNodes: document.querySelectorAll('*').length,
    detachedNodes: 0,
  }

  return snapshot
}

export function startMemoryTracking(
  intervalMs: number = 2000,
  durationMs: number = 60000,
): Promise<MemorySnapshot[]> {
  const snapshots: MemorySnapshot[] = []

  return new Promise((resolve) => {
    const interval = setInterval(() => {
      const snap = takeMemorySnapshot()
      if (snap) {
        snapshots.push(snap)
        if (snap.heapUtilization > 0.9) {
          console.warn(`[性能] 堆内存使用率过高: ${(snap.heapUtilization * 100).toFixed(1)}%`)
        }
        if (snap.domNodes > 5000) {
          console.warn(`[性能] DOM 节点数过多: ${snap.domNodes}，建议使用虚拟滚动`)
        }
      }
    }, intervalMs)

    setTimeout(() => {
      clearInterval(interval)
      console.log(`[性能] 内存追踪完成，共 ${snapshots.length} 个快照`)
      if (snapshots.length >= 2) {
        const first = snapshots[0]
        const last = snapshots[snapshots.length - 1]
        const growth = last.usedJSHeapSize - first.usedJSHeapSize
        if (growth > 10 * 1024 * 1024) {
          console.warn(`[性能] 可能的内存泄漏: 堆内存增长 ${(growth / 1024 / 1024).toFixed(1)}MB`)
        }
      }
      resolve(snapshots)
    }, durationMs)
  })
}

// ==================== Vue 组件性能分析 ====================

export function analyzeVueComponentRender(componentName: string): void {
  const perfEntries = performance.getEntriesByName(componentName, 'measure')
  if (perfEntries.length === 0) {
    console.log(`[性能] 未找到 ${componentName} 的性能记录`)
    return
  }

  const durations = perfEntries.map((e) => e.duration)
  const avg = durations.reduce((a, b) => a + b, 0) / durations.length
  const max = Math.max(...durations)
  console.log(`[性能] ${componentName}: 渲染${durations.length}次, avg=${avg.toFixed(1)}ms, max=${max.toFixed(1)}ms`)

  if (avg > 16.67) {
    console.warn(`[性能] ${componentName} 渲染时间超过一帧(16.67ms)，可能影响流畅度`)
  }
}

// ==================== 综合诊断 ====================

export async function runFullDiagnosis(): Promise<void> {
  console.group('[ERP 性能诊断]')

  // 1. DOM 审计
  console.group('1. DOM 审计')
  const domAudit = auditDOM()
  console.log(`总节点数: ${domAudit.totalNodes}`)
  console.log(`最大深度: ${domAudit.depth}`)
  console.log('重元素:', domAudit.heavyElements)
  if (domAudit.totalNodes > 3000) {
    console.warn(`DOM 节点过多(${domAudit.totalNodes})，建议使用虚拟滚动`)
  }
  console.groupEnd()

  // 2. 事件监听器审计
  console.group('2. 事件监听器审计')
  const eventAudit = auditEventListeners()
  for (const e of eventAudit) {
    console.log(`${e.eventType}: ${e.count} 个监听器`)
  }
  console.groupEnd()

  // 3. 内存快照
  console.group('3. 内存快照')
  const memSnapshot = takeMemorySnapshot()
  if (memSnapshot) {
    console.log(`已用堆: ${(memSnapshot.usedJSHeapSize / 1024 / 1024).toFixed(1)}MB`)
    console.log(`堆上限: ${(memSnapshot.jsHeapSizeLimit / 1024 / 1024).toFixed(1)}MB`)
    console.log(`利用率: ${(memSnapshot.heapUtilization * 100).toFixed(1)}%`)
  }
  console.groupEnd()

  // 4. 长任务监测 (5秒)
  console.group('4. 长任务监测 (5s)')
  const longTasks = await monitorLongTasks(5000)
  console.log(`检测到 ${longTasks.length} 个长任务`)
  console.groupEnd()

  console.groupEnd()
}

// 自动暴露到 window（仅开发模式）
if (import.meta.env?.DEV) {
  ;(window as any).__erp_perf__ = {
    auditDOM,
    monitorReflowRepaint,
    auditEventListeners,
    monitorLongTasks,
    takeMemorySnapshot,
    startMemoryTracking,
    runFullDiagnosis,
  }
  console.log('[ERP 性能工具] 已挂载到 window.__erp_perf__')
}

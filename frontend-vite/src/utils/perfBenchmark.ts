/**
 * 前端性能基准测试 - 使用 Performance API 测量核心操作耗时
 *
 * 运行方式: 在浏览器控制台执行 import('/src/utils/perfBenchmark.ts')
 * 或在 Vitest 中 import { runBenchmark } from '@/utils/perfBenchmark'
 */

interface BenchResult {
  label: string
  iterations: number
  times: number[]
  avg: number
  median: number
  p95: number
  min: number
  max: number
}

const results: BenchResult[] = []

function bench(label: string, fn: () => void | Promise<void>, iterations = 10): Promise<BenchResult> {
  return new Promise((resolve) => {
    const times: number[] = []
    let i = 0

    async function runOne() {
      const t0 = performance.now()
      await fn()
      const elapsed = performance.now() - t0
      times.push(elapsed)
      i++
      if (i < iterations) {
        requestAnimationFrame(runOne)
      } else {
        times.sort((a, b) => a - b)
        const result: BenchResult = {
          label,
          iterations,
          times,
          avg: times.reduce((s, v) => s + v, 0) / times.length,
          median: times[Math.floor(times.length / 2)],
          p95: times[Math.floor(times.length * 0.95)],
          min: times[0],
          max: times[times.length - 1],
        }
        results.push(result)
        const status = result.median < 200 ? '✓' : '✗'
        console.log(`${status} ${label}: avg=${result.avg.toFixed(1)}ms median=${result.median.toFixed(1)}ms p95=${result.p95.toFixed(1)}ms`)
        resolve(result)
      }
    }

    runOne()
  })
}

function generateMockItems(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    name: `产品_${String(i + 1).padStart(5, '0')}`,
    barcode: `BC${100000 + i}`,
    quantity: Math.floor(Math.random() * 500),
    customer: `客户_${String(Math.floor(Math.random() * 200)).padStart(4, '0')}`,
    status: ['pending', 'confirmed', 'completed'][Math.floor(Math.random() * 3)],
    date: '2024-01-15',
  }))
}

async function benchDOMRendering() {
  console.log('\n=== DOM 渲染性能 ===')

  const container = document.createElement('div')
  container.style.cssText = 'position:fixed;top:-9999px;left:-9999px;width:800px;height:600px;overflow:auto;'
  document.body.appendChild(container)

  for (const count of [100, 500, 1000, 5000, 10000, 20000]) {
    const items = generateMockItems(count)

    await bench(`DOM:render_${count}_rows_simple`, () => {
      container.innerHTML = ''
      const table = document.createElement('table')
      const tbody = document.createElement('tbody')
      for (const item of items) {
        const tr = document.createElement('tr')
        tr.innerHTML = `<td>${item.id}</td><td>${item.name}</td><td>${item.quantity}</td><td>${item.status}</td>`
        tbody.appendChild(tr)
      }
      table.appendChild(tbody)
      container.appendChild(table)
    }, 3)
  }

  document.body.removeChild(container)
}

async function benchDataProcessing() {
  console.log('\n=== 数据处理性能 ===')

  for (const count of [1000, 5000, 10000, 20000, 50000]) {
    const items = generateMockItems(count)

    await bench(`Data:filter_${count}_items`, () => {
      items.filter((item) => item.status === 'pending' && item.quantity > 100)
    })

    await bench(`Data:sort_${count}_items`, () => {
      ;[...items].sort((a, b) => a.name.localeCompare(b.name))
    })

    await bench(`Data:map_${count}_items`, () => {
      items.map((item) => ({ ...item, display: `${item.name} - ${item.quantity}` }))
    })

    await bench(`Data:groupby_${count}_items`, () => {
      const groups: Record<string, typeof items> = {}
      for (const item of items) {
        ;(groups[item.status] ??= []).push(item)
      }
    })
  }
}

async function benchVirtualScrollCalc() {
  console.log('\n=== 虚拟滚动计算性能 ===')

  const ITEM_HEIGHT = 48
  const CONTAINER_HEIGHT = 600
  const BUFFER = 10

  for (const count of [10000, 20000, 50000, 100000]) {
    await bench(`VScroll:calc_visible_${count}_items`, () => {
      for (let scrollTop = 0; scrollTop < count * ITEM_HEIGHT; scrollTop += CONTAINER_HEIGHT) {
        const startIdx = Math.max(0, Math.floor(scrollTop / ITEM_HEIGHT) - BUFFER)
        const visCount = Math.ceil(CONTAINER_HEIGHT / ITEM_HEIGHT) + BUFFER * 2
        const endIdx = Math.min(count, startIdx + visCount)
        const offsetY = startIdx * ITEM_HEIGHT
        void offsetY; void endIdx
      }
    })
  }
}

async function benchMemoryUsage() {
  console.log('\n=== 内存占用 ===')

  for (const count of [1000, 5000, 10000, 20000, 50000]) {
    const items = generateMockItems(count)

    if ((performance as any).memory) {
      const before = (performance as any).memory.usedJSHeapSize
      const copy = JSON.parse(JSON.stringify(items))
      const after = (performance as any).memory.usedJSHeapSize
      console.log(`  Memory:${count}_items: ${((after - before) / 1024 / 1024).toFixed(2)}MB`)
      void copy
    } else {
      const jsonSize = new Blob([JSON.stringify(items)]).size
      console.log(`  Memory:${count}_items: ${(jsonSize / 1024 / 1024).toFixed(2)}MB (JSON size)`)
    }
  }
}

export async function runBenchmark() {
  console.log('前端性能基准测试')
  console.log('='.repeat(60))

  await benchDOMRendering()
  await benchDataProcessing()
  await benchVirtualScrollCalc()
  await benchMemoryUsage()

  console.log('\n=== 汇总 ===')
  const passed = results.filter((r) => r.median < 200).length
  console.log(`通过: ${passed}/${results.length} (目标: median < 200ms)`)

  return results
}

export { results, bench }

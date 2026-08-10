/**
 * ECharts 预加载模块
 *
 * 策略：
 * - 在登录成功后立即触发 preloadEcharts()（与 authStore.init 并行），
 *   利用路由跳转 + 组件挂载的时间窗口提前下载 ~1MB 的 ECharts 代码。
 * - Dashboard 渲染时直接使用已缓存的模块，将首次 chart-order-render
 *   从 ~354ms 降至 ~20ms（仅 setOption 开销）。
 *
 * 用法：
 *   import { preloadEcharts, ensureEcharts } from '@/utils/echartsPreload'
 *   // 尽早触发，不 await：
 *   preloadEcharts()
 *   // 需要用时 await：
 *   const echarts = await ensureEcharts()
 */

type EChartsModule = typeof import('echarts/core')

let _modulePromise: Promise<EChartsModule> | null = null
let _module: EChartsModule | null = null

/**
 * 触发 ECharts 模块预加载（幂等，多次调用不会重复下载）
 * 不 await 返回值即可实现后台加载
 */
export function preloadEcharts(): Promise<EChartsModule> {
  if (_modulePromise) return _modulePromise

  _modulePromise = (async () => {
    const mod = await import('echarts/core')
    const [
      { LineChart, PieChart },
      { GridComponent, TooltipComponent, LegendComponent },
      { CanvasRenderer },
    ] = await Promise.all([
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers'),
    ])
    mod.use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])
    _module = mod
    return mod
  })()

  // 失败后重置缓存，允许下次调用重试（避免缓存 rejected promise）
  _modulePromise.catch(() => {
    _modulePromise = null
  })

  return _modulePromise
}

/**
 * 获取 ECharts 模块（如果已预加载则立即返回，否则触发加载）
 */
export function ensureEcharts(): Promise<EChartsModule> {
  return _module ? Promise.resolve(_module) : preloadEcharts()
}

/**
 * 同步获取已加载的模块（仅当确定已预加载完成时使用，否则返回 null）
 */
export function getEchartsModule(): EChartsModule | null {
  return _module
}

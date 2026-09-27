/**
 * ECharts 预加载模块
 *
 * 策略：
 * - 在登录成功后立即触发 preloadEcharts()（与 authStore.init 并行），
 *   利用路由跳转 + 组件挂载的时间窗口提前下载 ECharts 代码（按需打包 ~550KB）。
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

// 真正按需注册在 ./echartsSetup（静态命名导入 + echarts.use），本模块只负责
// 动态触发它；登录首屏因此不再包含 vendor-echarts。
type EChartsModule = typeof import('echarts/core')

let _promise: Promise<EChartsModule> | null = null
let _module: EChartsModule | null = null

/** 动态加载并缓存 echartsSetup（失败后清空缓存，允许重试）。 */
function loadEchartsModule(): Promise<EChartsModule> {
  if (!_promise) {
    _promise = import('./echartsSetup')
      .then((mod) => {
        _module = mod.default
        return mod.default
      })
      .catch((err) => {
        _promise = null
        throw err
      })
  }
  return _promise
}

/**
 * 触发 ECharts 模块预加载（幂等，多次调用不会重复下载）
 * 不 await 返回值即可实现后台加载
 */
export function preloadEcharts(): Promise<EChartsModule> {
  return loadEchartsModule()
}

/**
 * 获取 ECharts 模块（如果已预加载则立即返回，否则触发加载）
 */
export function ensureEcharts(): Promise<EChartsModule> {
  return loadEchartsModule()
}

/**
 * 同步获取已加载的模块（仅当确定已预加载完成时使用，否则返回 null）
 */
export function getEchartsModule(): EChartsModule | null {
  return _module
}

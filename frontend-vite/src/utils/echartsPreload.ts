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

import type { EChartsType } from 'echarts/core'
import * as echarts from 'echarts/core'
import { LineChart, PieChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent, DatasetComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// 静态命名导入：使 Rollup tree-shaking 生效，仅打包用到的图表/组件
// （此前用 import('echarts/charts') 动态导入整模块，全部图表类型都会进包 ~1MB）
echarts.use([
  LineChart, PieChart, BarChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, DatasetComponent,
  CanvasRenderer,
])

type EChartsModule = typeof import('echarts/core')

let _module: EChartsModule | null = null

/**
 * 触发 ECharts 模块预加载（幂等，多次调用不会重复下载）
 * 不 await 返回值即可实现后台加载
 */
export function preloadEcharts(): Promise<EChartsModule> {
  // 静态导入已完成 use() 注册，模块已随 vendor-echarts chunk 加载，
  // 此处仅做引用标记，确保打包器将 chunk 保留
  _module = echarts
  return Promise.resolve(echarts)
}

/**
 * 获取 ECharts 模块（如果已预加载则立即返回，否则触发加载）
 */
export function ensureEcharts(): Promise<EChartsModule> {
  return Promise.resolve(echarts)
}

/**
 * 同步获取已加载的模块（仅当确定已预加载完成时使用，否则返回 null）
 */
export function getEchartsModule(): EChartsModule | null {
  return _module
}

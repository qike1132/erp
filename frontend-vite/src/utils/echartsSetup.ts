/**
 * ECharts 按需注册模块。
 *
 * 这里保留“静态命名导入 + echarts.use()”，让 Rollup 能精确 tree-shaking；
 * 但整个文件通过 dynamic import(./echartsSetup) 加载，把约 400KB(gzip)
 * 的 vendor-echarts 移出登录页首屏，登录成功后再预加载。
 */
import * as echarts from 'echarts/core'
import { LineChart, PieChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent, DatasetComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart, PieChart, BarChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, DatasetComponent,
  CanvasRenderer,
])

export default echarts

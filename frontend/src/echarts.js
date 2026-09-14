/**
 * ECharts 按需注册（E03）。
 * 所有面板统一从此模块导入，避免 `import * as echarts from 'echarts'` 全量打包（原 1.71 MB 单包）。
 * 新增图表类型时，务必在此补充对应的 chart / component 注册，否则运行时会静默不渲染。
 */
import * as echarts from 'echarts/core'
import {
  MapChart,      // geo 底图（PanelMap）
  LinesChart,    // 航线、风向指示线
  EffectScatterChart, // 作业区波纹点、航点
  ScatterChart,  // 降水/雷暴点位符号、范围标签锚点
  CustomChart,   // 风险区多边形（custom series）
  LineChart      // SFI 历史与预测折线（PanelSfi）
} from 'echarts/charts'
import {
  GeoComponent,      // 地理坐标系
  TooltipComponent,  // 悬浮提示
  GridComponent,     // 直角坐标系（SFI 折线）
  MarkLineComponent, // SFI 80/60/40 阈值线
  GraphicComponent   // 图形元素（渐变等）
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import chinaJson from './assets/china.json'

echarts.use([
  MapChart, LinesChart, EffectScatterChart, ScatterChart, CustomChart, LineChart,
  GeoComponent, TooltipComponent, GridComponent, MarkLineComponent, GraphicComponent,
  CanvasRenderer
])

/** 产品范围限定为东北三省；从现有省级 GeoJSON 中裁出辽吉黑，避免显示无关区域。 */
const northeastNames = new Set(['辽宁省', '吉林省', '黑龙江省'])
const northeastJson = { ...chinaJson, features: chinaJson.features.filter(feature => northeastNames.has(feature.properties?.name)) }
echarts.registerMap('northeast', northeastJson)

export default echarts

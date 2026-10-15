import { LineChart, type LineSeriesOption } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  type GridComponentOption,
  type TooltipComponentOption,
} from 'echarts/components'
import { init, use as register, type ComposeOption } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'

export type TrendChartOption = ComposeOption<LineSeriesOption | GridComponentOption | TooltipComponentOption>

register([LineChart, GridComponent, TooltipComponent, SVGRenderer])

export const initTrendChart = (element: HTMLDivElement) => init(element, undefined, { renderer: 'svg' })

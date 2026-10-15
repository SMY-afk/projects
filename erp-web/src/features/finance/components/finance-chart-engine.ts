import { LineChart, PieChart, type LineSeriesOption, type PieSeriesOption } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  type GridComponentOption,
  type LegendComponentOption,
  type TooltipComponentOption,
} from 'echarts/components'
import { init, use as register, type ComposeOption } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'

export type FinanceChartOption = ComposeOption<
  LineSeriesOption | PieSeriesOption | GridComponentOption | LegendComponentOption | TooltipComponentOption
>

register([LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

export const initFinanceChart = (element: HTMLDivElement) => init(element, undefined, { renderer: 'svg' })

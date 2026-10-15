import { useEffect, useMemo, useRef } from 'react'
import { Card, Empty } from 'antd'
import type { ECharts } from 'echarts/core'
import type { FinanceTrendPoint } from '../types/finance.types'
import { formatFinanceAxis, formatFinanceMoney } from './finance-format'
import type { FinanceChartOption } from './finance-chart-engine'

const labels = {
  revenueAmountMinor: '销售收入',
  refundAmountMinor: '退款',
  feeAmountMinor: '费用',
  settlementAmountMinor: '结算金额',
} as const

const colors = {
  revenueAmountMinor: '#1677ff',
  refundAmountMinor: '#ff7875',
  feeAmountMinor: '#faad14',
  settlementAmountMinor: '#52c41a',
} as const

const keys = Object.keys(labels) as Array<keyof typeof labels>

function dayLabel(value: string) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return match ? `${match[2]}-${match[3]}` : value
}

function option(points: FinanceTrendPoint[], currency: string): FinanceChartOption {
  return {
    animationDuration: 350,
    color: keys.map((key) => colors[key]),
    grid: { left: 74, right: 24, top: 50, bottom: 38 },
    legend: { top: 4, itemWidth: 12, itemHeight: 8 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) =>
        typeof value === 'number' ? formatFinanceMoney(value, currency) : String(value ?? '--'),
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: points.map((point) => dayLabel(point.date)),
      axisTick: { show: false },
      axisLabel: { color: '#667085', hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: '#667085',
        formatter: (value: number) => formatFinanceAxis(value, currency),
      },
      splitLine: { lineStyle: { color: '#f0f2f5' } },
    },
    series: keys.map((key) => ({
      name: labels[key],
      type: 'line',
      data: points.map((point) => point[key]),
      smooth: 0.2,
      symbol: points.length > 14 ? 'none' : 'circle',
      lineStyle: { width: key === 'settlementAmountMinor' ? 3 : 2 },
      emphasis: { focus: 'series' },
    })),
  }
}

export function FinanceTrendChart({ points, currency }: { points: FinanceTrendPoint[]; currency: string }) {
  const elementRef = useRef<HTMLDivElement>(null)
  const chartOption = useMemo(() => option(points, currency), [currency, points])
  useEffect(() => {
    const element = elementRef.current
    if (!element || !points.length) return
    let chart: ECharts | undefined
    let observer: ResizeObserver | undefined
    let cancelled = false
    void import('./finance-chart-engine').then(({ initFinanceChart }) => {
      if (cancelled) return
      chart = initFinanceChart(element)
      chart.setOption(chartOption)
      if (typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(() => chart?.resize())
        observer.observe(element)
      }
    })
    return () => {
      cancelled = true
      observer?.disconnect()
      chart?.dispose()
    }
  }, [chartOption, points.length])
  return (
    <Card title="每日金额趋势" extra="按 UTC 自然日聚合">
      {points.length ? (
        <div ref={elementRef} className="finance-chart" role="img" aria-label="每日金额趋势图" />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前范围暂无趋势数据" />
      )}
    </Card>
  )
}

import { useEffect, useMemo, useRef } from 'react'
import { Card, Empty, Spin, Statistic, Typography } from 'antd'
import type { ECharts } from 'echarts/core'
import type { AnalyticsSnapshot, DataEnvelope } from '../types/data.types'
import type { TrendChartOption } from './trend-chart-engine'

type DataQuery<T> = {
  data?: DataEnvelope<T>
  error?: unknown
  isError?: boolean
  isLoading: boolean
}

type TrendDatum = {
  date: string
  label: string
  value: number | null
}

type TrendModel = {
  currency: string
  current: TrendDatum[]
  previous: TrendDatum[]
  movingAverage: Array<number | null>
  total: number
  dailyAverage: number
  maximum: number
  minimum: number
  changeRate: number | null
}

const moneyValue = (snapshot: AnalyticsSnapshot) => {
  const raw = snapshot.metrics.gmv ?? snapshot.metrics.gmvAmount
  if (raw && typeof raw === 'object' && typeof (raw as { amountMinor?: unknown }).amountMinor === 'number') {
    return (raw as { amountMinor: number }).amountMinor / 100
  }
  const numeric = typeof raw === 'number' ? raw : typeof raw === 'string' ? Number(raw) : Number.NaN
  return Number.isFinite(numeric) ? numeric : null
}

const dateLabel = (value: string, timezone?: string | null) => {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      timeZone: timezone ?? 'UTC',
    }).format(date)
  } catch {
    return '--'
  }
}

const toData = (snapshots: AnalyticsSnapshot[], timezone?: string | null) =>
  [...snapshots]
    .sort((left, right) => left.windowStart.localeCompare(right.windowStart))
    .map((snapshot) => ({
      date: snapshot.windowStart,
      label: dateLabel(snapshot.windowStart, timezone),
      value: moneyValue(snapshot),
    }))

const movingAverage = (values: Array<number | null>, windowSize = 7) =>
  values.map((_value, index) => {
    if (index < windowSize - 1) return null
    const window = values.slice(index - windowSize + 1, index + 1)
    if (window.some((value) => value === null)) return null
    return window.reduce<number>((total, value) => total + (value ?? 0), 0) / windowSize
  })

const buildTrendModel = (
  currentSnapshots: AnalyticsSnapshot[],
  previousSnapshots: AnalyticsSnapshot[],
  timezone?: string | null,
): TrendModel | null => {
  const current = toData(currentSnapshots, timezone)
  const values = current.map((point) => point.value).filter((value): value is number => value !== null)
  if (!values.length) return null
  const previous = toData(previousSnapshots, timezone)
  const previousValues = previous.map((point) => point.value).filter((value): value is number => value !== null)
  const total = values.reduce((sum, value) => sum + value, 0)
  const previousTotal = previousValues.reduce((sum, value) => sum + value, 0)
  return {
    currency: currentSnapshots[0]?.currency ?? previousSnapshots[0]?.currency ?? 'USD',
    current,
    previous,
    movingAverage: movingAverage(current.map((point) => point.value)),
    total,
    dailyAverage: total / values.length,
    maximum: Math.max(...values),
    minimum: Math.min(...values),
    changeRate: previousTotal > 0 ? (total - previousTotal) / previousTotal : null,
  }
}

const formatMoney = (value: number, currency: string) =>
  new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)

const formatAxisMoney = (value: number, currency: string) => {
  const symbol = currency === 'USD' ? '$' : `${currency} `
  if (Math.abs(value) >= 1_000_000) return `${symbol}${(value / 1_000_000).toFixed(1)}M`
  if (Math.abs(value) >= 1_000) return `${symbol}${(value / 1_000).toFixed(1)}K`
  return `${symbol}${Math.round(value)}`
}

const tooltipHtml = (params: unknown, model: TrendModel) => {
  const items = Array.isArray(params)
    ? (params as Array<{ seriesName?: string; dataIndex?: number; value?: unknown; color?: string }>)
    : []
  const index = items[0]?.dataIndex ?? 0
  const rows = items
    .filter((item) => typeof item.value === 'number')
    .map((item) => {
      const date = item.seriesName === '上一周期' ? model.previous[index]?.label : model.current[index]?.label
      return `<div class="data-trend-tooltip-row"><span><i style="background:${item.color}"></i>${item.seriesName} · ${date ?? '--'}</span><strong>${formatMoney(item.value as number, model.currency)}</strong></div>`
    })
    .join('')
  return `<div class="data-trend-tooltip"><b>${model.current[index]?.label ?? '--'}</b>${rows}</div>`
}

const chartOption = (model: TrendModel): TrendChartOption => ({
  animationDuration: 350,
  grid: { left: 72, right: 24, top: 20, bottom: 46 },
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'line', lineStyle: { color: '#91caff', type: 'dashed' } },
    backgroundColor: 'rgba(255,255,255,.98)',
    borderColor: '#d9d9d9',
    formatter: (params) => tooltipHtml(params, model),
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: model.current.map((point) => point.label),
    axisLabel: {
      color: '#667085',
      hideOverlap: true,
      interval: Math.max(0, Math.ceil(model.current.length / 8) - 1),
    },
    axisLine: { lineStyle: { color: '#d9d9d9' } },
    axisTick: { show: false },
  },
  yAxis: {
    type: 'value',
    min: 0,
    splitNumber: 5,
    axisLabel: { color: '#667085', formatter: (value: number) => formatAxisMoney(value, model.currency) },
    splitLine: { lineStyle: { color: '#f0f2f5' } },
  },
  series: [
    {
      name: '当前周期',
      type: 'line',
      data: model.current.map((point) => point.value),
      smooth: 0.22,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { color: '#1677ff', width: 2.5 },
      itemStyle: { color: '#fff', borderColor: '#1677ff', borderWidth: 2 },
      emphasis: { focus: 'series', scale: 1.7 },
      areaStyle: {
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 0,
          y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(22,119,255,.24)' },
            { offset: 1, color: 'rgba(22,119,255,.02)' },
          ],
        },
      },
    },
    {
      name: '上一周期',
      type: 'line',
      data: model.current.map((_point, index) => model.previous[index]?.value ?? null),
      smooth: 0.22,
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { color: '#98a2b3', width: 2, type: 'dashed' },
      itemStyle: { color: '#fff', borderColor: '#98a2b3', borderWidth: 1.5 },
      emphasis: { focus: 'series', scale: 1.7 },
    },
    {
      name: '7 日平均',
      type: 'line',
      data: model.movingAverage,
      symbol: 'none',
      smooth: 0.35,
      lineStyle: { color: '#13a8a8', width: 2 },
      emphasis: { focus: 'series' },
    },
  ],
})

function AmountTrendChart({ model }: { model: TrendModel }) {
  const chartElement = useRef<HTMLDivElement>(null)
  const option = useMemo(() => chartOption(model), [model])

  useEffect(() => {
    const element = chartElement.current
    if (!element) return
    let chart: ECharts | undefined
    let observer: ResizeObserver | undefined
    let cancelled = false
    void import('./trend-chart-engine').then(({ initTrendChart }) => {
      if (cancelled) return
      chart = initTrendChart(element)
      chart.setOption(option)
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
  }, [option])

  return <div ref={chartElement} className="data-trend-chart" role="img" aria-label="成交金额趋势" />
}

const queryNote = (query: DataQuery<unknown[]>) => {
  if (query.isError) return '趋势数据加载失败，请稍后刷新。'
  if (query.data?.freshness.isStale) return '暂无本地快照，重新同步后将在此展示。'
  return '当前时间范围暂无趋势数据。'
}

export function TrendCard({
  query,
  previousQuery,
  timezone,
  periodDays,
}: {
  query: DataQuery<AnalyticsSnapshot[]>
  previousQuery?: DataQuery<AnalyticsSnapshot[]>
  timezone?: string | null
  periodDays?: number
}) {
  const model = useMemo(
    () => buildTrendModel(query.data?.data ?? [], previousQuery?.data?.data ?? [], timezone),
    [previousQuery?.data?.data, query.data?.data, timezone],
  )
  const loading = query.isLoading || Boolean(previousQuery?.isLoading)
  const change = model?.changeRate ?? null
  return (
    <Card
      title="趋势"
      extra={<Typography.Text type="secondary">近 {periodDays ?? model?.current.length ?? 0} 天</Typography.Text>}
    >
      {model && (
        <>
          <div className="data-trend-summary">
            <div className="data-trend-primary-stat">
              <Statistic title="成交金额" value={formatMoney(model.total, model.currency)} />
              <Typography.Text className={change !== null && change < 0 ? 'data-trend-down' : 'data-trend-up'}>
                {change === null
                  ? '上期暂无可比数据'
                  : `${change >= 0 ? '↑' : '↓'} ${Math.abs(change * 100).toFixed(1)}% 较上期`}
              </Typography.Text>
            </div>
            <Statistic title="日均成交额" value={formatMoney(model.dailyAverage, model.currency)} />
            <Statistic title="最高成交额" value={formatMoney(model.maximum, model.currency)} />
            <Statistic title="最低成交额" value={formatMoney(model.minimum, model.currency)} />
          </div>
          <div className="data-trend-legend" aria-label="趋势图例">
            <span>
              <i className="data-trend-current" />
              当前周期
            </span>
            <span>
              <i className="data-trend-previous" />
              上一周期
            </span>
            <span>
              <i className="data-trend-average" />7 日平均
            </span>
          </div>
        </>
      )}
      <div className="data-trend-frame">
        {loading && <Spin className="data-trend-loading" />}
        {model ? (
          <AmountTrendChart model={model} />
        ) : (
          <div className="data-trend-chart" role="img" aria-label="趋势图表空状态" />
        )}
        {!model && !loading && (
          <Empty className="data-trend-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description={queryNote(query)} />
        )}
      </div>
    </Card>
  )
}

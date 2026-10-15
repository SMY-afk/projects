import { useState, type Dispatch, type SetStateAction } from 'react'
import { ClockCircleOutlined, LineChartOutlined, RightOutlined, ShopOutlined } from '@ant-design/icons'
import { Image, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type {
  DashboardProductPerformance,
  DashboardQueryParams,
  DashboardSnapshot,
  DistributionMetric,
} from '../types/dashboard.types'
import { formatMoney, formatNumber, platformLabel } from './dashboard-format'
import { DashboardFilters } from './dashboard-filters'
import { trendValues } from './dashboard-metric-utils'
import { DashboardMetricCard, type DashboardMetric } from './dashboard-metrics'
import { dashboardProductRowKey } from './dashboard-row-key'
import { DashboardTrendInsights } from './dashboard-trend-insights'
import { emptyAffiliateOperations } from './dashboard-affiliate-defaults'
import { DashboardAffiliateOperations } from './dashboard-affiliate-operations'
import { DashboardAffiliateRankings } from './dashboard-affiliate-rankings'
import { DashboardSwitch, OrderDistribution, SalesDistribution } from './dashboard-widgets'
import '@/pages/dashboard/dashboard-page.css'

interface DashboardContentProps {
  snapshot: DashboardSnapshot
  params: DashboardQueryParams
  loading: boolean
  onChange: Dispatch<SetStateAction<DashboardQueryParams>>
  onRefresh: () => void
}

function dashboardMetrics(snapshot: DashboardSnapshot, params: DashboardQueryParams): DashboardMetric[] {
  const { current, previous, points } = snapshot.trend
  const averagePricePoints = points.map((point) => (point.salesVolume ? point.salesAmountMinor / point.salesVolume : 0))
  const primary: DashboardMetric[] = [
    {
      key: 'sales',
      label: '销售额',
      value: formatMoney(current.salesAmountMinor, params.currency),
      category: '销售',
      current: current.salesAmountMinor,
      previous: previous.salesAmountMinor,
      points: trendValues(points, 'salesAmountMinor'),
    },
    {
      key: 'net-sales',
      label: snapshot.netSalesEstimated ? '净销售额（估算）' : '净销售额',
      value: formatMoney(current.netSalesAmountMinor, params.currency),
      category: '销售',
      current: current.netSalesAmountMinor,
      previous: previous.netSalesAmountMinor,
      points: trendValues(points, 'netSalesAmountMinor'),
    },
    {
      key: 'orders',
      label: '订单量',
      value: formatNumber(current.orderCount),
      category: '订单',
      current: current.orderCount,
      previous: previous.orderCount,
      points: trendValues(points, 'orderCount'),
    },
    {
      key: 'volume',
      label: '销量',
      value: formatNumber(current.salesVolume),
      category: '销售',
      current: current.salesVolume,
      previous: previous.salesVolume,
      points: trendValues(points, 'salesVolume'),
    },
    {
      key: 'average-price',
      label: '商品均价',
      value: formatMoney(current.averageItemPriceMinor, params.currency),
      category: '销售',
      current: current.averageItemPriceMinor,
      previous: previous.averageItemPriceMinor,
      points: averagePricePoints,
    },
    {
      key: 'cancelled',
      label: '取消订单数',
      value: formatNumber(current.cancelledOrderCount),
      category: '订单',
      current: current.cancelledOrderCount,
      previous: previous.cancelledOrderCount,
      positiveWhenUp: false,
    },
  ]
  const fulfilment: DashboardMetric[] = snapshot.fulfilmentMetrics.map((item, index) => ({
    key: `fulfilment-${index}-${item.label}`,
    label: item.label,
    value: formatNumber(item.value),
    category: '履约',
    status: '当前待处理',
  }))
  return [
    ...primary,
    ...fulfilment,
    {
      key: 'shops',
      label: params.shopId ? '当前店铺' : '已接入店铺',
      value: params.shopId ? 1 : snapshot.filters.shops.length,
      category: '店铺',
      status: params.shopId ? '单店视图' : '全部店铺',
    },
  ]
}

function updatedAt(snapshot: DashboardSnapshot, timezone: string) {
  return new Date(snapshot.generatedAt).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: timezone,
    hour12: false,
  })
}

export function DashboardContent({ snapshot, params, loading, onChange, onRefresh }: DashboardContentProps) {
  const [salesMetric, setSalesMetric] = useState<DistributionMetric>('salesAmountMinor')
  const metrics = dashboardMetrics(snapshot, params)
  const columns: ColumnsType<DashboardProductPerformance> = [
    {
      title: '商品',
      width: 360,
      render: (_, row) => (
        <div className="performance-product">
          {row.imageUrl ? (
            <Image alt={row.name} height={44} preview src={row.imageUrl} width={44} />
          ) : (
            <span className="performance-product-empty">暂无图片</span>
          )}
          <div className="performance-product-copy">
            <Tooltip title={row.name}>
              <b>{row.name}</b>
            </Tooltip>
            <small>SKU：{row.sku}</small>
          </div>
        </div>
      ),
    },
    { title: '产品 ID', dataIndex: 'productId', ellipsis: true, width: 150 },
    { title: '平台', dataIndex: 'platform', render: (value: string) => platformLabel(value), width: 90 },
    { title: '店铺 / 站点', dataIndex: 'store', ellipsis: true, width: 160 },
    { title: '销量', dataIndex: 'salesVolume', align: 'right', render: formatNumber, width: 90 },
    {
      title: '销售额',
      dataIndex: 'salesAmountMinor',
      align: 'right',
      render: (value: number) => formatMoney(value, params.currency),
      width: 130,
    },
    {
      title: snapshot.netSalesEstimated ? '净销售额（估算）' : '净销售额',
      dataIndex: 'netSalesAmountMinor',
      align: 'right',
      render: (value: number) => formatMoney(value, params.currency),
      width: 150,
    },
  ]

  return (
    <main className={`dashboard-page${loading ? ' dashboard-loading' : ''}`}>
      <header className="dashboard-header">
        <div>
          <h1>Dashboard</h1>
          <p>集中查看店铺销售、订单履约与商品表现。</p>
        </div>
        <span className="dashboard-header-time">
          <ClockCircleOutlined /> 数据更新于 {updatedAt(snapshot, params.timezone)}
        </span>
      </header>
      <DashboardFilters
        filters={snapshot.filters}
        loading={loading}
        onChange={onChange}
        onRefresh={onRefresh}
        params={params}
      />
      <div className="dashboard-canvas">
        <section className="dashboard-brief">
          <div className="dashboard-brief-icon">
            <LineChartOutlined />
          </div>
          <div>
            <small>经营数据快报 · 店铺汇总</small>
            <strong>今日经营概览与待处理事项</strong>
            <p>汇总所选范围内的销售、订单和履约数据，帮助快速定位异常变化。</p>
          </div>
          <a href="#product-performance">
            查看商品明细 <RightOutlined />
          </a>
        </section>

        <div className="dashboard-section-heading">
          <div>
            <small>KEY METRICS</small>
            <h2>核心指标</h2>
          </div>
          <span>
            <ShopOutlined /> {params.shopId ? '当前为单店视图' : `共 ${snapshot.filters.shops.length} 家店铺`}
          </span>
        </div>
        <section className="dashboard-metric-grid">
          {metrics.map((metric) => (
            <DashboardMetricCard key={metric.key} metric={metric} />
          ))}
        </section>

        <DashboardTrendInsights onChange={onChange} params={params} snapshot={snapshot} />

        <DashboardAffiliateOperations
          currency={params.currency}
          data={snapshot.affiliateOperations ?? emptyAffiliateOperations}
        />

        <section className="dashboard-insights-grid">
          <article className="dashboard-panel distribution-panel">
            <div className="dashboard-panel-title">
              <div>
                <small>CHANNEL MIX</small>
                <h2>销售分布</h2>
              </div>
              <DashboardSwitch
                labels={[
                  { label: '销售额', value: 'salesAmountMinor' },
                  { label: '销量', value: 'salesVolume' },
                  { label: '订单', value: 'orderCount' },
                ]}
                value={salesMetric}
                onChange={setSalesMetric}
              />
            </div>
            <SalesDistribution currency={params.currency} items={snapshot.salesDistribution} metric={salesMetric} />
          </article>
          <article className="dashboard-panel order-panel">
            <div className="dashboard-panel-title">
              <div>
                <small>ORDER INSIGHTS</small>
                <h2>订单地区分布</h2>
              </div>
              <DashboardSwitch
                labels={[
                  { label: '近7天', value: 'last7d' },
                  { label: '近14天', value: 'last14d' },
                  { label: '近28天', value: 'last28d' },
                ]}
                value={params.orderRange}
                onChange={(orderRange) => onChange((current) => ({ ...current, orderRange }))}
              />
            </div>
            <OrderDistribution items={snapshot.orderDistribution} />
          </article>
          <article className="dashboard-panel inventory-panel">
            <div className="dashboard-panel-title">
              <div>
                <small>INVENTORY</small>
                <h2>库存状态</h2>
              </div>
              <span>待接入</span>
            </div>
            <div className="inventory-placeholder">
              <b>--</b>
              <span>库存数据暂未同步</span>
              <small>当前改版保留展示位，不改变原有数据范围。</small>
            </div>
          </article>
        </section>

        <DashboardAffiliateRankings params={params} />

        <section className="dashboard-panel table-panel" id="product-performance">
          <div className="dashboard-panel-title">
            <div>
              <small>PRODUCT PERFORMANCE</small>
              <h2>商品业绩表现</h2>
            </div>
            <span>{snapshot.productPerformance.length} 条记录</span>
          </div>
          <Table
            columns={columns}
            dataSource={snapshot.productPerformance}
            locale={{ emptyText: '当前筛选条件暂无商品销售数据' }}
            pagination={false}
            rowKey={dashboardProductRowKey}
            scroll={{ x: 1130 }}
            size="small"
            tableLayout="fixed"
          />
        </section>
      </div>
    </main>
  )
}

import { Button, Card, Input, message, Select, Space, Table, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { LogisticsSectionNav } from '../components/logistics-section-nav'
import { LogisticsStatusExportButton } from '../components/logistics-status-export-button'
import { LogisticsOrderCategoryTabs } from '../components/logistics-order-category-tabs'
import { orderElapsed, orderCategories, type LogisticsOrderCategory } from '../utils/logistics-order-categories'
import { logisticsStatusApi } from '../api/logistics-status.api'
import { useLogisticsShopOptionsQuery } from '../queries/logistics.queries'
import type { LogisticsAlertPhase, LogisticsOrderAlert, LogisticsStatusLive, LogisticsStatusOrder } from '../types/logistics-status.types'
import { LogisticsOrderWarningCards } from '../components/logistics-order-warning-cards'
import { overdueDuration, warningLabels } from '../utils/logistics-warning-presentation'
import { LogisticsOrderStatusDrawer } from '../components/logistics-order-status-drawer'
import { LogisticsAlertSettings } from '../components/logistics-alert-settings'
import { shippingMethodLabel } from '../utils/logistics-shipping-method'
import {
  formatTime,
  packageLabels,
  trackingLabels,
  packageSummary,
  cachedTracking,
} from '../utils/logistics-status-presentation'
import './logistics-page.css'

export default function LogisticsStatusPage() {
  const [params, setParams] = useState({
    page: 1,
    pageSize: 20,
    shopId: undefined as string | undefined,
    orderNumber: undefined as string | undefined,
    category: 'pending_shipment' as LogisticsOrderCategory | undefined,
    alert: undefined as LogisticsOrderAlert | undefined,
    alertPhase: undefined as LogisticsAlertPhase | undefined,
  })
  const [orderNumberInput, setOrderNumberInput] = useState('')
  const [liveByOrder, setLiveByOrder] = useState<Record<string, LogisticsStatusLive>>({})
  const [selectedOrder, setSelectedOrder] = useState<LogisticsStatusOrder | null>(null)
  const [refreshingId, setRefreshingId] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  const category = orderCategories.find((item) => item.key === params.category)
  const title = params.alert ? `${warningLabels[params.alert]} · ${params.alertPhase === 'upcoming' ? '快超时' : '已超时'}` : `${category?.label}订单`
  const currentLive = (order: LogisticsStatusOrder) => {
    const live = liveByOrder[order.id]
    return live && (!order.officialCheckedAt || Date.parse(live.checkedAt) >= Date.parse(order.officialCheckedAt))
      ? live
      : undefined
  }
  const shops = useLogisticsShopOptionsQuery()
  const query = useQuery({
    queryKey: ['logistics', 'status', params],
    queryFn: () => logisticsStatusApi.list(params),
    refetchInterval: 30_000,
  })

  const refreshOne = async (order: LogisticsStatusOrder) => {
    setRefreshingId(order.id)
    try {
      const live = await logisticsStatusApi.refresh(order.id)
      setLiveByOrder((current) => ({ ...current, [order.id]: live }))
      setSelectedOrder(order)
      void query.refetch()
    } catch {
      void message.error('官方物流查询失败，请稍后重试或检查店铺授权')
    } finally {
      setRefreshingId(null)
    }
  }

  const columns = [
    { title: '店铺', dataIndex: 'shopName' },
    { title: '订单号', dataIndex: 'orderNumber' },
    { title: '订单创建时间', dataIndex: 'orderCreatedAt', render: formatTime },
    {
      title: params.alert ? params.alertPhase === 'upcoming' ? '剩余时间（最紧急优先）' : '超时时长（最长优先）' : category?.elapsed,
      render: (_: unknown, order: LogisticsStatusOrder) =>
        params.alert ? (() => {
          const seconds = order.alerts?.[params.alert]
          return seconds === undefined ? '—' : <Tag color={seconds < 0 ? 'gold' : 'red'}>
            {seconds < 0 ? '剩余' : '超时'} {overdueDuration(Math.abs(seconds))}
          </Tag>
        })() : params.category === 'partial_shipping' ? (
          <Tag color="orange">特殊情况：部分发货</Tag>
        ) : (
          orderElapsed(
            {
              ...order,
              platformStatus: currentLive(order)?.platformStatus ?? order.platformStatus,
              deliveredAt: currentLive(order)?.deliveredAt ?? order.deliveredAt,
            },
            now,
          )
        ),
    },
    {
      title: '订单状态',
      dataIndex: 'platformStatus',
      render: (value: string, order: LogisticsStatusOrder) => {
        const status = currentLive(order)?.platformStatus ?? value
        return packageLabels[status] ?? status
      },
    },
    {
      title: '物流方式',
      render: (_: unknown, order: LogisticsStatusOrder) => {
        const source = currentLive(order) ?? order
        return shippingMethodLabel(source.shippingType, source.fulfillmentType)
      },
    },
    {
      title: '物流状态（官方查询）',
      render: (_: unknown, order: LogisticsStatusOrder) => {
        const live = currentLive(order)
        const status = live ? live.trackingStatus : order.officialTrackingStatus
        const cached = cachedTracking(order)
        return status ? (
          <Tag color={status === 'exception' ? 'red' : status === 'delivered' ? 'green' : 'blue'}>
            {trackingLabels[status] ?? status}
          </Tag>
        ) : live || order.officialCheckedAt ? (
          '官方暂无轨迹'
        ) : cached ? (
          <span title="上次官方同步结果">{cached}</span>
        ) : (
          '待查询'
        )
      },
    },
    {
      title: '包裹状态',
      render: (_: unknown, order: LogisticsStatusOrder) =>
        packageSummary(currentLive(order)?.packages ?? order.packages),
    },
    {
      title: 'ERP同步时间',
      render: (_: unknown, order: LogisticsStatusOrder) =>
        formatTime(order.erpSyncedAt),
    },
    {
      title: '官方查询时间',
      render: (_: unknown, order: LogisticsStatusOrder) =>
        formatTime(currentLive(order)?.checkedAt ?? order.officialCheckedAt),
    },
    {
      title: '操作',
      render: (_: unknown, order: LogisticsStatusOrder) => (
        <Button
          type="link"
          loading={refreshingId === order.id}
          disabled={Boolean(refreshingId && refreshingId !== order.id)}
          onClick={() => void refreshOne(order)}
        >
          查看物流
        </Button>
      ),
    },
  ]

  const selectedLive = selectedOrder ? liveByOrder[selectedOrder.id] : null
  return (
    <Space className="logistics-page" orientation="vertical" size="large">
      <div>
        <Button onClick={() => window.history.back()}>返回</Button>
        <Typography.Title level={2}>物流状态</Typography.Title>
        <Typography.Text type="secondary">
          后台自动同步订单时更新ERP同步时间；查看物流只更新官方查询时间，物流轨迹由后台分批持续更新。
        </Typography.Text>
      </div>
      <LogisticsSectionNav />
      <LogisticsAlertSettings hours={query.data?.warnings?.leadHours ?? 3} onSaved={() => query.refetch()} />
      <LogisticsOrderWarningCards warnings={query.data?.warnings} selected={params.alert} phase={params.alertPhase} onSelect={(alert, alertPhase) => {
        setParams((current) => ({ ...current, alert, alertPhase, category: undefined, page: 1 }))
      }} />
      <Card
        title={title}
        extra={
          <LogisticsStatusExportButton
            shopId={params.shopId}
            orderNumber={params.orderNumber}
            shopName={shops.data?.find((shop) => shop.id === params.shopId)?.shopName}
            disabled={Boolean(refreshingId)}
            category={params.category}
            alert={params.alert}
            alertPhase={params.alertPhase}
          />
        }
      >
        <LogisticsOrderCategoryTabs
          value={params.category}
          counts={query.data?.categoryCounts}
          onChange={(category) => setParams((current) => ({ ...current, category, alert: undefined, alertPhase: undefined, page: 1 }))}
        />
        {query.isError && (
          <Typography.Paragraph type="warning">
            订单数据读取失败，请稍后重试。
          </Typography.Paragraph>
        )}
        <Space wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear
            loading={shops.isLoading}
            options={(shops.data ?? []).map((shop) => ({ label: shop.shopName, value: shop.id }))}
            placeholder="全部店铺"
            style={{ width: 220 }}
            value={params.shopId}
            onChange={(shopId) => setParams((current) => ({ ...current, shopId, page: 1 }))}
          />
          <Input.Search
            aria-label="订单号查询"
            placeholder="输入完整订单号查询"
            enterButton="查询"
            allowClear
            maxLength={100}
            style={{ width: 320, maxWidth: '100%' }}
            value={orderNumberInput}
            onChange={(event) => {
              setOrderNumberInput(event.target.value)
              if (!event.target.value) setParams((current) => ({ ...current, orderNumber: undefined, page: 1 }))
            }}
            onSearch={(value) =>
              setParams((current) => ({ ...current, orderNumber: value.trim() || undefined, page: 1 }))
            }
          />
          <Button
            onClick={() => {
              setOrderNumberInput('')
              setParams((current) => ({ ...current, page: 1, shopId: undefined, orderNumber: undefined, alert: undefined, alertPhase: undefined, category: 'pending_shipment' }))
            }}
          >
            重置
          </Button>
        </Space>
        <Table<LogisticsStatusOrder>
          columns={columns}
          dataSource={query.data?.items ?? []}
          loading={query.isLoading}
          rowKey="id"
          locale={{ emptyText: query.isError ? '订单加载失败，请重试' : `暂无${title}` }}
          scroll={{ x: 1920 }}
          pagination={{
            current: params.page,
            pageSize: params.pageSize,
            total: query.data?.total ?? 0,
            onChange: (page) => setParams((current) => ({ ...current, page })),
          }}
        />
      </Card>
      <LogisticsOrderStatusDrawer
        order={query.data?.items.find((order) => order.id === selectedOrder?.id) ?? selectedOrder}
        live={selectedLive}
        refreshing={Boolean(refreshingId)}
        onClose={() => setSelectedOrder(null)}
      />
    </Space>
  )
}

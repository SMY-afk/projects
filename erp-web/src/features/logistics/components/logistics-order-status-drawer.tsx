import { Card, Drawer, Space, Timeline, Typography } from 'antd'
import type { LogisticsStatusLive, LogisticsStatusOrder } from '../types/logistics-status.types'
import { LogisticsStatusExportButton } from './logistics-status-export-button'
import { formatTime, packageLabels, trackingLabels } from '../utils/logistics-status-presentation'

export function LogisticsOrderStatusDrawer({
  order,
  live,
  refreshing,
  onClose,
}: {
  order: LogisticsStatusOrder | null
  live?: LogisticsStatusLive | null
  refreshing: boolean
  onClose: () => void
}) {
  return (
    <Drawer
      title={order ? `订单 ${order.orderNumber} · 官方物流状态` : '官方物流状态'}
      open={Boolean(order)}
      onClose={onClose}
      size={560}
      extra={order && <LogisticsStatusExportButton order={order} disabled={refreshing} />}
    >
      {live && (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          <div>
            <Typography.Text strong>
              最新轨迹：{trackingLabels[live.trackingStatus ?? ''] ?? '暂无轨迹'}
            </Typography.Text>
            <br />
            <Typography.Text type="secondary">ERP同步时间：{formatTime(order?.erpSyncedAt)}</Typography.Text>
            <br />
            <Typography.Text type="secondary">官方查询时间：{formatTime(live.checkedAt)}</Typography.Text>
          </div>
          <Card size="small" title="包裹">
            {live.packages.length
              ? live.packages.map((item) => (
                  <div key={item.packageId}>
                    {item.packageId} · {packageLabels[item.packageStatus] ?? item.packageStatus} ·{' '}
                    {item.carrierName ?? '承运商未知'} · {item.trackingNumberMasked ?? '暂无运单号'}
                  </div>
                ))
              : '暂无包裹数据'}
          </Card>
          <Card size="small" title="物流轨迹">
            {live.events.length ? (
              <Timeline
                items={live.events.map((event) => ({
                  children: `${formatTime(event.occurredAt)} · ${trackingLabels[event.status] ?? event.status}${event.description ? ` · ${event.description}` : ''}`,
                }))}
              />
            ) : (
              '官方接口暂无轨迹'
            )}
          </Card>
        </Space>
      )}
    </Drawer>
  )
}

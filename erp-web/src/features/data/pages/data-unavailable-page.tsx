import { Alert, Card, Space, Tag, Typography } from 'antd'

const pendingMetrics = ['视频播放与观看人数', '直播观看人数', '归因 GMV 与归因订单', '退款金额与净 GMV']

export default function DataUnavailablePage({
  title = '真实数据暂不可用',
  description = 'TikTok Shop Analytics 的真实接口响应与指标口径尚在核验。本页不会显示 Mock、0 值或推测数据。',
}: {
  title?: string
  description?: string
}) {
  return (
    <Space direction="vertical" size="large" style={{ display: 'flex' }}>
      <Typography.Title level={2}>数据</Typography.Title>
      <Alert description={description} message={title} showIcon type="info" />
      <Card title="待确认指标">
        <Space size={[8, 8]} wrap>
          {pendingMetrics.map((metric) => (
            <Tag key={metric}>待确认：{metric}</Tag>
          ))}
        </Space>
        <Typography.Paragraph style={{ marginBottom: 0, marginTop: 16 }} type="secondary">
          完成官方字段与测试店铺只读探针验证后，才会开放对应指标。
        </Typography.Paragraph>
      </Card>
    </Space>
  )
}

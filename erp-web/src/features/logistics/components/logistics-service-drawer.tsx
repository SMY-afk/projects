import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Space, Table, Tag, Typography } from 'antd'
import type { LogisticsShippingQuote } from '../types/logistics.types'
import { formatDeliveryEstimate, formatShippingFee, shippingQuoteKey } from './logistics-shipping-view-model'

interface LogisticsServiceDrawerProps {
  open: boolean
  loading: boolean
  quotes: LogisticsShippingQuote[]
  selected: LogisticsShippingQuote | null
  onClose: () => void
  onRefresh: () => void
  onSelect: (quote: LogisticsShippingQuote) => void
  onConfirm: () => void
}

export function LogisticsServiceDrawer({
  open,
  loading,
  quotes,
  selected,
  onClose,
  onRefresh,
  onSelect,
  onConfirm,
}: LogisticsServiceDrawerProps) {
  return (
    <Drawer
      destroyOnHidden
      extra={
        <Button icon={<ReloadOutlined />} loading={loading} onClick={onRefresh}>
          重新试算
        </Button>
      }
      footer={
        <div className="logistics-drawer-footer">
          <Typography.Text type="secondary">
            {selected ? `已选 ${selected.carrierName} / ${selected.serviceName}` : '请选择一项物流服务'}
          </Typography.Text>
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button disabled={!selected} onClick={onConfirm} type="primary">
              确认选择
            </Button>
          </Space>
        </div>
      }
      onClose={onClose}
      open={open}
      title="选择物流服务"
      width={760}
    >
      <Alert
        message="费用与时效为试算结果，最终金额以物流商账单为准。"
        showIcon
        style={{ marginBottom: 16 }}
        type="info"
      />
      <Table<LogisticsShippingQuote>
        columns={[
          { title: '物流商', dataIndex: 'carrierName', width: 150 },
          { title: '服务', dataIndex: 'serviceName', width: 160 },
          { title: '预估费用', render: (_, quote) => formatShippingFee(quote), width: 130 },
          { title: '预计时效', render: (_, quote) => formatDeliveryEstimate(quote), width: 120 },
          {
            title: '说明',
            render: (_, quote) =>
              quote.warnings.length ? (
                <Space size={[4, 4]} wrap>
                  {quote.warnings.map((warning) => (
                    <Tag color="gold" key={warning}>
                      {warning}
                    </Tag>
                  ))}
                </Space>
              ) : (
                <Tag color="green">可用</Tag>
              ),
          },
        ]}
        dataSource={quotes}
        loading={loading}
        locale={{ emptyText: loading ? '正在试算' : '暂无可用物流服务' }}
        onRow={(quote) => ({ onClick: () => onSelect(quote) })}
        pagination={false}
        rowClassName={(quote) =>
          selected && shippingQuoteKey(quote) === shippingQuoteKey(selected) ? 'is-selected' : ''
        }
        rowKey={shippingQuoteKey}
        rowSelection={{
          onSelect,
          selectedRowKeys: selected ? [shippingQuoteKey(selected)] : [],
          type: 'radio',
        }}
      />
    </Drawer>
  )
}

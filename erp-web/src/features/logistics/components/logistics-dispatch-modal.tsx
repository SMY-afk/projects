import { ExclamationCircleOutlined } from '@ant-design/icons'
import { Alert, Descriptions, Modal, Table, Tag, Typography } from 'antd'
import type {
  LogisticsCarrier,
  LogisticsCarrierService,
  LogisticsPackage,
  LogisticsTaskItem,
  LogisticsWaybill,
} from '../types/logistics.types'
import { resolveDispatchLines } from './logistics-shipping-view-model'

interface LogisticsDispatchModalProps {
  open: boolean
  loading: boolean
  packageItem: LogisticsPackage
  taskItems: LogisticsTaskItem[]
  waybill: LogisticsWaybill
  carrier?: LogisticsCarrier
  service?: LogisticsCarrierService
  onCancel: () => void
  onConfirm: () => void
}

export function LogisticsDispatchModal({
  open,
  loading,
  packageItem,
  taskItems,
  waybill,
  carrier,
  service,
  onCancel,
  onConfirm,
}: LogisticsDispatchModalProps) {
  const lines = resolveDispatchLines(packageItem, taskItems)
  const total = lines.reduce((sum, line) => sum + line.quantity, 0)
  return (
    <Modal
      cancelText="返回检查"
      confirmLoading={loading}
      okButtonProps={{ danger: true }}
      okText="确认并发货"
      onCancel={onCancel}
      onOk={onConfirm}
      open={open}
      title={
        <span>
          <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
          二次确认发货
        </span>
      }
      width={760}
    >
      <Alert
        message="发货后包裹和运单将进入已发货状态，并异步回写销售平台。请确认以下信息无误。"
        showIcon
        style={{ marginBottom: 16 }}
        type="warning"
      />
      <Descriptions
        column={2}
        items={[
          { label: '包裹', children: packageItem.packageNumber },
          { label: '商品总数', children: `${total} 件` },
          { label: '物流商', children: carrier?.name ?? '-' },
          { label: '物流服务', children: service?.name ?? '-' },
          { label: 'ERP 运单号', children: <Typography.Text copyable>{waybill.waybillNumber}</Typography.Text> },
          { label: '物流追踪号', children: waybill.trackingNumberMasked ?? '-' },
        ]}
      />
      <Table<(typeof lines)[number]>
        columns={[
          { title: 'SKU', dataIndex: 'sku', width: 160 },
          { title: '商品', dataIndex: 'productName' },
          { title: '规格', dataIndex: 'specification', width: 140 },
          { title: '发货数量', dataIndex: 'quantity', width: 100, render: (value: number) => <Tag>{value}</Tag> },
        ]}
        dataSource={lines}
        pagination={false}
        rowKey="id"
        size="small"
      />
    </Modal>
  )
}

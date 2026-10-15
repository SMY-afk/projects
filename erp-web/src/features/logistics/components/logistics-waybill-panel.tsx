import {
  CloudDownloadOutlined,
  CloudServerOutlined,
  FilePdfOutlined,
  PrinterOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Form, Input, Popconfirm, Space, Tabs, Tag, Typography } from 'antd'
import type {
  LogisticsCarrier,
  LogisticsCarrierService,
  LogisticsShippingQuote,
  LogisticsWaybill,
} from '../types/logistics.types'
import { formatDeliveryEstimate, formatShippingFee } from './logistics-shipping-view-model'

export interface ManualWaybillFields {
  trackingNumber: string
  externalWaybillId?: string
}

interface LogisticsWaybillPanelProps {
  selectedQuote: LogisticsShippingQuote | null
  selectedCarrier?: LogisticsCarrier
  currentWaybill?: LogisticsWaybill
  currentCarrier?: LogisticsCarrier
  currentService?: LogisticsCarrierService
  creating: boolean
  cancelling: boolean
  uploading: boolean
  onChooseService: () => void
  onCreateManual: (values: ManualWaybillFields) => void
  onCreateOnline: () => void
  onCancelWaybill: () => void
  onDownloadLabel: () => void
  onReprintLabel: () => void
  onUploadLabel: (file?: File) => void
  onOpenDispatch: () => void
}

const waybillStatusLabels: Record<LogisticsWaybill['status'], string> = {
  created: '待面单',
  label_ready: '面单就绪',
  shipped: '已发货',
  in_transit: '运输中',
  delivered: '已签收',
  exception: '异常',
  cancelled: '已取消',
}

export function LogisticsWaybillPanel(props: LogisticsWaybillPanelProps) {
  if (props.currentWaybill) return <CurrentWaybill {...props} waybill={props.currentWaybill} />
  return <CreateWaybill {...props} />
}

function CurrentWaybill({
  waybill,
  currentCarrier,
  currentService,
  cancelling,
  uploading,
  onCancelWaybill,
  onDownloadLabel,
  onReprintLabel,
  onUploadLabel,
  onOpenDispatch,
}: LogisticsWaybillPanelProps & { waybill: LogisticsWaybill }) {
  const labelReady = waybill.status === 'label_ready'
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <Descriptions
        bordered
        column={2}
        items={[
          {
            label: '状态',
            children: <Tag color={labelReady ? 'green' : 'blue'}>{waybillStatusLabels[waybill.status]}</Tag>,
          },
          { label: 'ERP 运单号', children: <Typography.Text copyable>{waybill.waybillNumber}</Typography.Text> },
          { label: '物流商', children: currentCarrier?.name ?? '-' },
          { label: '服务', children: currentService?.name ?? '-' },
          { label: '追踪号', children: waybill.trackingNumberMasked ?? '未提供' },
          { label: '外部单号', children: waybill.externalWaybillId ?? '-' },
        ]}
      />
      {!labelReady && <Alert message="请先上传或在线获取面单，面单就绪后才能确认发货。" showIcon type="warning" />}
      <Space wrap>
        <Button disabled={!labelReady} icon={<CloudDownloadOutlined />} onClick={onDownloadLabel}>
          下载面单
        </Button>
        <Button disabled={!labelReady} icon={<PrinterOutlined />} onClick={onReprintLabel}>
          重新打印
        </Button>
        <Button icon={<UploadOutlined />} loading={uploading}>
          <label className="logistics-file-label">
            上传面单
            <input
              accept="application/pdf,image/png,text/plain"
              hidden
              type="file"
              onChange={(event) => onUploadLabel(event.target.files?.[0])}
            />
          </label>
        </Button>
        <Popconfirm title="确认取消当前运单？" onConfirm={onCancelWaybill}>
          <Button danger loading={cancelling}>
            取消运单
          </Button>
        </Popconfirm>
        <Button disabled={!labelReady} onClick={onOpenDispatch} type="primary">
          确认发货
        </Button>
      </Space>
    </Space>
  )
}

function CreateWaybill({
  selectedQuote,
  selectedCarrier,
  creating,
  onChooseService,
  onCreateManual,
  onCreateOnline,
}: LogisticsWaybillPanelProps) {
  const onlineAvailable = Boolean(selectedCarrier && selectedCarrier.adapterKey !== 'manual')
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <Card
        extra={<Button onClick={onChooseService}>{selectedQuote ? '重新选择' : '选择物流服务'}</Button>}
        size="small"
        title="已选物流服务"
      >
        {selectedQuote ? (
          <Descriptions
            column={4}
            items={[
              { label: '物流商', children: selectedQuote.carrierName },
              { label: '服务', children: selectedQuote.serviceName },
              { label: '预估费用', children: formatShippingFee(selectedQuote) },
              { label: '预计时效', children: formatDeliveryEstimate(selectedQuote) },
            ]}
          />
        ) : (
          <Typography.Text type="secondary">尚未选择物流商及服务</Typography.Text>
        )}
      </Card>
      <Tabs
        items={[
          {
            key: 'manual',
            label: '人工运单',
            children: (
              <Form<ManualWaybillFields> layout="vertical" onFinish={onCreateManual}>
                <Form.Item
                  label="物流追踪号"
                  name="trackingNumber"
                  rules={[{ required: true, message: '请输入人工运单号' }]}
                >
                  <Input maxLength={128} placeholder="扫描或输入物流商运单号" />
                </Form.Item>
                <Form.Item label="物流商外部单号（可选）" name="externalWaybillId">
                  <Input maxLength={128} />
                </Form.Item>
                <Button disabled={!selectedQuote} htmlType="submit" loading={creating} type="primary">
                  创建人工运单
                </Button>
              </Form>
            ),
          },
          {
            key: 'online',
            label: '在线创建',
            children: (
              <Space orientation="vertical" size="middle">
                <Alert
                  message={
                    onlineAvailable ? '将调用物流商 API 创建运单并获取面单。' : '所选服务尚未接通在线物流商 Adapter。'
                  }
                  showIcon
                  type={onlineAvailable ? 'info' : 'warning'}
                />
                <Button
                  disabled={!selectedQuote || !onlineAvailable}
                  icon={<CloudServerOutlined />}
                  loading={creating}
                  onClick={onCreateOnline}
                  type="primary"
                >
                  在线创建运单
                </Button>
              </Space>
            ),
          },
        ]}
      />
      <Typography.Text type="secondary">
        <FilePdfOutlined /> 人工运单创建后需要上传面单；在线运单由物流商接口返回运单号和面单。
      </Typography.Text>
    </Space>
  )
}

import { App, Button, Input, InputNumber, Modal, Select, Space, Table, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { returnsApi } from '../api/returns.api'
import { useCreateReturnRequestMutation } from '../queries/returns.queries'
import type { ReturnEligibility, ReturnRequestType } from '../types/returns.types'

const reasonOptions = [
  { label: '不再需要 / 改变主意', value: 'changed_mind' },
  { label: '商品破损', value: 'damaged' },
  { label: '数量不一致', value: 'quantity_mismatch' },
  { label: '商品错误', value: 'wrong_item' },
  { label: '质量问题', value: 'quality_issue' },
  { label: '其他', value: 'other' },
]

interface Props {
  open: boolean
  initialOrderReference?: string
  onClose: () => void
}

export function ReturnRequestModal({ open, initialOrderReference = '', onClose }: Props) {
  const { message } = App.useApp()
  const createMutation = useCreateReturnRequestMutation()
  const [reference, setReference] = useState(initialOrderReference)
  const [eligibility, setEligibility] = useState<ReturnEligibility | null>(null)
  const [loadingOrder, setLoadingOrder] = useState(false)
  const [requestType, setRequestType] = useState<ReturnRequestType>('return')
  const [reasonCode, setReasonCode] = useState('changed_mind')
  const [customerNote, setCustomerNote] = useState('')
  const [quantities, setQuantities] = useState<Record<string, number>>({})

  const close = () => {
    setReference(initialOrderReference)
    setEligibility(null)
    setQuantities({})
    setCustomerNote('')
    onClose()
  }

  const selectedCount = useMemo(
    () => Object.values(quantities).reduce((sum, quantity) => sum + quantity, 0),
    [quantities],
  )

  const loadOrder = async () => {
    if (!reference.trim()) return
    setLoadingOrder(true)
    try {
      const record = await returnsApi.getEligibility(reference.trim())
      setEligibility(record)
      setQuantities({})
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '原订单加载失败')
    } finally {
      setLoadingOrder(false)
    }
  }

  const submit = async () => {
    if (!eligibility || selectedCount < 1) {
      void message.warning('请至少选择一件可退商品')
      return
    }
    try {
      await createMutation.mutateAsync({
        orderId: eligibility.orderId,
        requestType,
        reasonCode,
        customerNote: customerNote.trim() || null,
        items: eligibility.items
          .filter((item) => (quantities[item.orderLineId] ?? 0) > 0)
          .map((item) => ({
            orderLineId: item.orderLineId,
            requestedQuantity: quantities[item.orderLineId],
            reasonCode,
            note: null,
          })),
      })
      void message.success('退换货申请已创建，等待审核')
      close()
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '申请创建失败')
    }
  }

  return (
    <Modal
      open={open}
      title="创建退换货申请"
      width={880}
      onCancel={close}
      onOk={() => void submit()}
      okText="提交申请"
      confirmLoading={createMutation.isPending}
      okButtonProps={{ disabled: !eligibility || selectedCount < 1 }}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            value={reference}
            placeholder="输入平台订单号或 ERP 订单 ID"
            onChange={(event) => setReference(event.target.value)}
            onPressEnter={() => void loadOrder()}
          />
          <Button loading={loadingOrder} onClick={() => void loadOrder()}>
            校验原订单
          </Button>
        </Space.Compact>
        <Space wrap>
          <Select
            value={requestType}
            options={[
              { label: '退货', value: 'return' },
              { label: '换货', value: 'exchange' },
            ]}
            onChange={setRequestType}
            style={{ width: 140 }}
          />
          <Select value={reasonCode} options={reasonOptions} onChange={setReasonCode} style={{ width: 220 }} />
          <Input
            value={customerNote}
            placeholder="客户备注（可选）"
            onChange={(event) => setCustomerNote(event.target.value)}
            style={{ width: 360 }}
          />
        </Space>
        {eligibility && (
          <>
            <Typography.Text>
              原订单：{eligibility.orderNumber}；本次选择数量：{selectedCount}
            </Typography.Text>
            <Table
              rowKey="orderLineId"
              pagination={false}
              dataSource={eligibility.items}
              columns={[
                { title: '商品', dataIndex: 'productName' },
                { title: 'SKU', dataIndex: 'sellerSku', render: (value: string | null) => value || '-' },
                { title: '原数量', dataIndex: 'orderedQuantity' },
                { title: '已申请', dataIndex: 'requestedQuantity' },
                { title: '最大可退', dataIndex: 'availableQuantity' },
                {
                  title: '本次数量',
                  render: (_, item) => (
                    <InputNumber
                      min={0}
                      max={item.availableQuantity}
                      disabled={item.availableQuantity < 1}
                      value={quantities[item.orderLineId] ?? 0}
                      onChange={(value) => setQuantities((current) => ({ ...current, [item.orderLineId]: value ?? 0 }))}
                    />
                  ),
                },
              ]}
            />
          </>
        )}
      </Space>
    </Modal>
  )
}

import { Button, DatePicker, Input, Select, Space } from 'antd'
import type { Dayjs } from 'dayjs'
import type { ReturnRequestStatus, ReturnRequestType, ReturnShopOption } from '../types/returns.types'

const returnStatusLabels: Record<ReturnRequestStatus, string> = {
  pending_review: '待审核',
  approved: '已批准',
  rejected: '已拒绝',
  cancelled: '已取消',
}

interface ReturnListFiltersProps {
  shops: ReturnShopOption[]
  shopsLoading: boolean
  shopId?: string
  requestType?: ReturnRequestType
  status?: ReturnRequestStatus
  reason: string
  rma: string
  appliedRange: [Dayjs | null, Dayjs | null] | null
  onShopChange: (value?: string) => void
  onTypeChange: (value?: ReturnRequestType) => void
  onStatusChange: (value?: ReturnRequestStatus) => void
  onReasonChange: (value: string) => void
  onRmaChange: (value: string) => void
  onAppliedRangeChange: (value: [Dayjs | null, Dayjs | null] | null) => void
  onReset: () => void
}

export function ReturnListFilters(props: ReturnListFiltersProps) {
  return (
    <Space wrap style={{ marginBottom: 16 }}>
      <Select
        allowClear
        loading={props.shopsLoading}
        value={props.shopId}
        onChange={props.onShopChange}
        options={props.shops.map((shop) => ({ value: shop.id, label: shop.shopName }))}
        style={{ width: 180 }}
        placeholder="全部店铺"
      />
      <Select<ReturnRequestType>
        allowClear
        placeholder="全部类型"
        value={props.requestType}
        onChange={props.onTypeChange}
        options={[
          { label: '退货', value: 'return' },
          { label: '换货', value: 'exchange' },
          { label: '仅退款', value: 'refund' },
        ]}
        style={{ width: 140 }}
      />
      <Select<ReturnRequestStatus>
        allowClear
        placeholder="全部状态"
        value={props.status}
        onChange={props.onStatusChange}
        options={Object.entries(returnStatusLabels).map(([value, label]) => ({ value, label }))}
        style={{ width: 140 }}
      />
      <Input
        allowClear
        placeholder="原因代码/说明"
        value={props.reason}
        onChange={(event) => props.onReasonChange(event.target.value)}
        style={{ width: 190 }}
      />
      <DatePicker.RangePicker
        value={props.appliedRange}
        onChange={(value) => props.onAppliedRangeChange(value ? [value[0], value[1]] : null)}
        placeholder={['申请开始时间', '申请结束时间']}
      />
      <Input
        allowClear
        placeholder="RMA 编号"
        value={props.rma}
        onChange={(event) => props.onRmaChange(event.target.value)}
        style={{ width: 170 }}
      />
      <Button onClick={props.onReset}>重置</Button>
    </Space>
  )
}

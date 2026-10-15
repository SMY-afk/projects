import { Card, DatePicker, Select, Space } from 'antd'
import type { Dayjs } from 'dayjs'
import type { ReactNode } from 'react'
import type { FinanceShopOption } from '../types/finance.types'
import { isFinanceDateDisabled } from '../utils/finance-range'

export function FinanceListToolbar({
  shops,
  shopId,
  range,
  currency,
  maxDate,
  extra,
  actions,
  onShopChange,
  onRangeChange,
  onCurrencyChange,
}: {
  shops: FinanceShopOption[]
  shopId?: string
  range: [Dayjs, Dayjs]
  currency: string
  maxDate: Dayjs
  extra?: ReactNode
  actions?: ReactNode
  onShopChange: (value: string) => void
  onRangeChange: (value: [Dayjs, Dayjs]) => void
  onCurrencyChange: (value: string) => void
}) {
  return (
    <Card className="finance-filter-card" size="small">
      <div className="finance-filter-bar">
        <label className="finance-filter-field">
          <span>店铺</span>
          <Select
            aria-label="财务店铺"
            value={shopId}
            onChange={onShopChange}
            options={shops.map((shop) => ({ value: shop.id, label: shop.shopName }))}
            style={{ width: 190 }}
          />
        </label>
        <label className="finance-filter-field">
          <span>日期</span>
          <DatePicker.RangePicker
            aria-label="财务日期范围"
            allowClear={false}
            maxDate={maxDate}
            value={range}
            disabledDate={(current, info) => isFinanceDateDisabled(current, info.from, maxDate)}
            onChange={(value) => value?.[0] && value[1] && onRangeChange([value[0], value[1]])}
          />
        </label>
        <label className="finance-filter-field">
          <span>币种</span>
          <Select
            aria-label="财务币种"
            value={currency}
            onChange={onCurrencyChange}
            options={['USD', 'EUR', 'GBP', 'JPY'].map((value) => ({ value, label: value }))}
            style={{ width: 92 }}
          />
        </label>
        {extra}
        {actions && <Space className="finance-filter-actions">{actions}</Space>}
      </div>
    </Card>
  )
}

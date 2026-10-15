import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Card, DatePicker, Select, Space, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import type { FinanceShopOption } from '../types/finance.types'
import { isFinanceDateDisabled } from '../utils/finance-range'

export type FinanceBasisFilter = 'all' | 'settled' | 'estimated'

export function FinanceFilters({
  shops,
  shopId,
  range,
  currency,
  basis,
  maxDate,
  refreshing,
  exporting,
  onShopChange,
  onRangeChange,
  onCurrencyChange,
  onBasisChange,
  onRefresh,
  onExport,
}: {
  shops: FinanceShopOption[]
  shopId?: string
  range: [Dayjs, Dayjs]
  currency: string
  basis: FinanceBasisFilter
  maxDate: Dayjs
  refreshing: boolean
  exporting: boolean
  onShopChange: (value: string) => void
  onRangeChange: (value: [Dayjs, Dayjs]) => void
  onCurrencyChange: (value: string) => void
  onBasisChange: (value: FinanceBasisFilter) => void
  onRefresh: () => void
  onExport: () => void
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
          <span>结算日期</span>
          <DatePicker.RangePicker
            aria-label="财务日期范围"
            allowClear={false}
            maxDate={maxDate}
            value={range}
            disabledDate={(current, info) => isFinanceDateDisabled(current, info.from, maxDate)}
            onChange={(value) => value?.[0] && value[1] && onRangeChange([value[0], value[1]])}
          />
          <Typography.Text type="secondary">最多 30 个自然日，按店铺时区换算</Typography.Text>
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
        <label className="finance-filter-field">
          <span>数据口径</span>
          <Select
            aria-label="财务数据口径"
            value={basis}
            onChange={onBasisChange}
            options={[
              { value: 'all', label: '全部口径' },
              { value: 'settled', label: '最终结算' },
              { value: 'estimated', label: '估算数据' },
            ]}
            style={{ width: 120 }}
          />
        </label>
        <Space className="finance-filter-actions" wrap>
          <Button icon={<ReloadOutlined />} loading={refreshing} onClick={onRefresh}>
            刷新
          </Button>
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={onExport}>
            导出结算单
          </Button>
        </Space>
      </div>
    </Card>
  )
}

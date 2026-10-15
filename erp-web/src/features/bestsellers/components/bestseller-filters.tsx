import { ReloadOutlined, SyncOutlined } from '@ant-design/icons'
import { Button, DatePicker, Select, Space } from 'antd'
import type { Dayjs } from 'dayjs'
import type {
  BestsellerAuthorType,
  BestsellerCurrency,
  BestsellerRoute,
  BestsellerShop,
  BestsellerTimeSlot,
} from '../types/bestseller.types'

export function BestsellerFilters({
  shops,
  shopId,
  date,
  maxDate,
  timeSlot,
  currency,
  entity,
  authorType,
  canSync,
  syncing,
  onShopChange,
  onDateChange,
  onTimeSlotChange,
  onCurrencyChange,
  onAuthorTypeChange,
  onRefresh,
  onSync,
}: {
  shops: BestsellerShop[]
  shopId?: string
  date: Dayjs
  maxDate: Dayjs
  timeSlot: BestsellerTimeSlot
  currency: BestsellerCurrency
  entity: BestsellerRoute
  authorType: BestsellerAuthorType
  canSync: boolean
  syncing: boolean
  onShopChange: (value: string) => void
  onDateChange: (value: Dayjs) => void
  onTimeSlotChange: (value: BestsellerTimeSlot) => void
  onCurrencyChange: (value: BestsellerCurrency) => void
  onAuthorTypeChange: (value: BestsellerAuthorType) => void
  onRefresh: () => void
  onSync: () => void
}) {
  return (
    <div className="bestseller-filter-bar">
      <label className="bestseller-filter-field">
        <span>店铺</span>
        <Select
          aria-label="店铺"
          onChange={onShopChange}
          options={shops.map((shop) => ({ label: shop.shopName, value: shop.id }))}
          value={shopId}
        />
      </label>
      <label className="bestseller-filter-field">
        <span>结束日期</span>
        <DatePicker
          allowClear={false}
          aria-label="结束日期"
          maxDate={maxDate}
          onChange={(value) => value && onDateChange(value)}
          value={date}
        />
      </label>
      <label className="bestseller-filter-field">
        <span>统计周期</span>
        <Select<BestsellerTimeSlot>
          aria-label="统计周期"
          onChange={onTimeSlotChange}
          options={[
            { label: '最近 1 天', value: '1D' },
            { label: '最近 7 天', value: '7D' },
            { label: '最近 30 天', value: '30D' },
          ]}
          value={timeSlot}
        />
      </label>
      <label className="bestseller-filter-field">
        <span>币种</span>
        <Select<BestsellerCurrency>
          aria-label="币种"
          onChange={onCurrencyChange}
          options={[
            { label: 'USD', value: 'USD' },
            { label: '店铺本地币种', value: 'LOCAL' },
          ]}
          value={currency}
        />
      </label>
      {entity === 'creators' && (
        <label className="bestseller-filter-field">
          <span>创作者类型</span>
          <Select<BestsellerAuthorType>
            aria-label="创作者类型"
            onChange={onAuthorTypeChange}
            options={[
              { label: '全部', value: 'ALL' },
              { label: '官方账号', value: 'OFFICIAL' },
              { label: '渠道账号', value: 'CHANNEL' },
              { label: '联盟达人', value: 'AFFILIATE' },
            ]}
            value={authorType}
          />
        </label>
      )}
      <Space className="bestseller-filter-actions">
        <Button icon={<ReloadOutlined />} onClick={onRefresh}>
          刷新
        </Button>
        <Button
          disabled={!canSync}
          icon={<SyncOutlined spin={syncing} />}
          loading={syncing}
          onClick={onSync}
          type="primary"
        >
          同步当前榜单
        </Button>
      </Space>
    </div>
  )
}

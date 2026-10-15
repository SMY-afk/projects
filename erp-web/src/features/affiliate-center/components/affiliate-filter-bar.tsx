import { Card, DatePicker, Select, Space, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import type { AffiliateShop } from '../types/affiliate-center.types'

export interface AffiliateFilters {
  shopId: string
  from: string
  to: string
  currency: string
}

interface Props {
  dateRangeLabel?: string
  enable60DayPreset?: boolean
  filters: AffiliateFilters
  latestAvailableDay?: string
  loading: boolean
  shops: AffiliateShop[]
  tikTokToday?: string
  onChange: (filters: AffiliateFilters) => void
}

export function AffiliateFilterBar({
  dateRangeLabel = '日期范围',
  enable60DayPreset = false,
  filters,
  latestAvailableDay: latestDay,
  loading,
  shops,
  tikTokToday,
  onChange,
}: Props) {
  const currencies = [...new Set(shops.map((shop) => shop.currency).filter((item): item is string => Boolean(item)))]
  const range: [Dayjs, Dayjs] = [dayjs(filters.from), dayjs(filters.to)]
  const latestAvailableDay = latestDay ? dayjs(latestDay) : dayjs(filters.to).startOf('day')
  const dateContext =
    tikTokToday && latestDay && tikTokToday !== latestDay
      ? `TK 当地日期：${tikTokToday}；数据截至：${latestDay}`
      : tikTokToday
        ? `TK 当地日期：${tikTokToday}`
        : undefined
  const presets: Array<{ label: string; value: [Dayjs, Dayjs] }> = [
    { label: '今天', value: [latestAvailableDay, latestAvailableDay] },
    { label: '最近 7 天', value: [latestAvailableDay.subtract(6, 'day'), latestAvailableDay] },
    { label: '最近 30 天', value: [latestAvailableDay.subtract(29, 'day'), latestAvailableDay] },
  ]
  if (enable60DayPreset) {
    presets.push({ label: '近两个月', value: [latestAvailableDay.subtract(59, 'day'), latestAvailableDay] })
  }

  return (
    <Card size="small">
      <Space className="affiliate-filter-bar" size="middle" wrap>
        <label className="affiliate-filter-field">
          <Typography.Text type="secondary">店铺</Typography.Text>
          <Select
            aria-label="店铺"
            loading={loading}
            options={shops.map((shop) => ({ label: shop.shopName, value: shop.id }))}
            value={filters.shopId || undefined}
            onChange={(shopId) => {
              const shop = shops.find((item) => item.id === shopId)
              onChange({ ...filters, shopId, currency: shop?.currency ?? filters.currency })
            }}
          />
        </label>
        <label className="affiliate-filter-field">
          <Typography.Text type="secondary">{dateRangeLabel}</Typography.Text>
          <DatePicker.RangePicker
            allowClear={false}
            aria-label={dateRangeLabel}
            disabledDate={(current) => current.isAfter(latestAvailableDay, 'day')}
            presets={presets}
            value={range}
            onChange={(value) => {
              if (!value?.[0] || !value[1]) return
              onChange({ ...filters, from: value[0].format('YYYY-MM-DD'), to: value[1].format('YYYY-MM-DD') })
            }}
          />
        </label>
        <label className="affiliate-filter-field affiliate-currency-field">
          <Typography.Text type="secondary">币种</Typography.Text>
          <Select
            aria-label="币种"
            options={(currencies.length ? currencies : [filters.currency]).map((currency) => ({
              label: currency,
              value: currency,
            }))}
            value={filters.currency}
            onChange={(currency) => onChange({ ...filters, currency })}
          />
        </label>
        {dateContext && <Typography.Text type="secondary">{dateContext}</Typography.Text>}
      </Space>
    </Card>
  )
}

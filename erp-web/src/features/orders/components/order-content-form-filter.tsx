import { Select } from 'antd'
import type { AffiliateContentForm } from '../types/order.types'
import { affiliateContentFormOptions } from './order-filter-options'

export function OrderContentFormFilter({
  value,
  onChange,
}: {
  value?: AffiliateContentForm
  onChange: (value?: AffiliateContentForm) => void
}) {
  return (
    <Select
      allowClear
      aria-label="内容形式筛选"
      onChange={onChange}
      options={affiliateContentFormOptions}
      placeholder="内容形式"
      popupMatchSelectWidth={false}
      size="small"
      style={{ width: 132 }}
      value={value}
    />
  )
}

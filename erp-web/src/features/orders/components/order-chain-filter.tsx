import { Cascader } from 'antd'
import { orderTypeOptions } from './order-filter-options'

export function OrderChainFilter({ value, onChange }: { value?: string[]; onChange: (path?: string[]) => void }) {
  return (
    <Cascader
      allowClear
      aria-label="成交链路筛选"
      changeOnSelect
      displayRender={(labels) => labels.at(-1)}
      onChange={(path) => onChange(path.length ? path : undefined)}
      options={orderTypeOptions}
      placeholder="成交链路"
      popupMatchSelectWidth={false}
      size="small"
      style={{ width: 180 }}
      value={value}
    />
  )
}

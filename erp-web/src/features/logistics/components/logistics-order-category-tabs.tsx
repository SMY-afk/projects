import { Tabs } from 'antd'
import { orderCategories, type LogisticsOrderCategory } from '../utils/logistics-order-categories'

export function LogisticsOrderCategoryTabs({
  value,
  counts,
  onChange,
}: {
  value?: LogisticsOrderCategory
  counts?: Partial<Record<LogisticsOrderCategory, number>>
  onChange: (value: LogisticsOrderCategory) => void
}) {
  return (
    <>
      {!value && <style>{'.logistics-warning-filter-tabs .ant-tabs-ink-bar { display: none; }'}</style>}
      <Tabs
        className={!value ? 'logistics-warning-filter-tabs' : undefined}
        activeKey={value ?? 'warnings'}
        onChange={(key) => onChange(key as LogisticsOrderCategory)}
        items={orderCategories.map(({ key, label }) => ({ key, label: `${label} (${counts?.[key] ?? '—'})` }))}
      />
    </>
  )
}

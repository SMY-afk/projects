import { useMemo, type Dispatch, type SetStateAction } from 'react'
import { QuestionCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Select, Tooltip } from 'antd'
import type { DashboardQueryParams, DashboardSnapshot } from '../types/dashboard.types'
import { platformLabel } from './dashboard-format'
import { DashboardSwitch } from './dashboard-widgets'

export function DashboardFilters({
  filters,
  loading,
  params,
  onChange,
  onRefresh,
}: {
  filters: DashboardSnapshot['filters']
  loading: boolean
  params: DashboardQueryParams
  onChange: Dispatch<SetStateAction<DashboardQueryParams>>
  onRefresh: () => void
}) {
  const visibleShops = useMemo(
    () =>
      filters.shops.filter(
        (shop) =>
          (!params.platform || shop.platform === params.platform) && (!params.site || shop.site === params.site),
      ),
    [filters.shops, params.platform, params.site],
  )
  const sites = useMemo(
    () =>
      Array.from(
        new Set(
          filters.shops
            .filter((shop) => !params.platform || shop.platform === params.platform)
            .map((shop) => shop.site)
            .filter((site): site is string => Boolean(site)),
        ),
      ),
    [filters.shops, params.platform],
  )
  const setFilter = (patch: Partial<DashboardQueryParams>) => onChange((current) => ({ ...current, ...patch }))
  return (
    <div className="dashboard-filters">
      <div className="dashboard-filter-selects">
        <Select
          allowClear
          options={filters.platforms.map((value) => ({ value, label: platformLabel(value) }))}
          placeholder="全部平台"
          size="small"
          value={params.platform}
          onChange={(platform) => setFilter({ platform, site: undefined, shopId: undefined })}
        />
        <Select
          allowClear
          options={sites.map((value) => ({ value, label: value }))}
          placeholder="全部站点"
          size="small"
          value={params.site}
          onChange={(site) => setFilter({ site, shopId: undefined })}
        />
        <Select
          allowClear
          options={visibleShops.map((shop) => ({ value: shop.id, label: shop.name }))}
          placeholder="全部店铺"
          size="small"
          value={params.shopId}
          onChange={(shopId) => {
            const timezone = filters.shops.find((shop) => shop.id === shopId)?.timezone
            setFilter({ shopId, ...(timezone ? { timezone } : {}) })
          }}
        />
        <Select
          options={filters.currencies.map((value) => ({ value, label: value }))}
          size="small"
          value={params.currency}
          onChange={(currency) => setFilter({ currency })}
        />
      </div>
      <div className="dashboard-filter-actions">
        <DashboardSwitch
          labels={[
            { label: '近7天', value: 'last7d' },
            { label: '近30天', value: 'last30d' },
            { label: '上月', value: 'lastMonth' },
            { label: '今年', value: 'year' },
          ]}
          value={params.trendRange}
          onChange={(trendRange) => setFilter({ trendRange })}
        />
        <Button
          aria-label="刷新仪表盘"
          className="dashboard-refresh"
          icon={<ReloadOutlined spin={loading} />}
          onClick={onRefresh}
        >
          刷新
        </Button>
        <Tooltip title="金额按所选币种聚合，不进行汇率换算。库存暂未同步。">
          <Button aria-label="帮助" icon={<QuestionCircleOutlined />} type="text" />
        </Tooltip>
      </div>
    </div>
  )
}

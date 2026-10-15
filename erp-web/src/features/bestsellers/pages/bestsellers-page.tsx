import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, Space, Tabs, Typography } from 'antd'
import dayjs from 'dayjs'
import { useSearchParams } from 'react-router'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { useAuth } from '@/auth/use-auth'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { isBestsellersMock } from '../api/bestsellers.api'
import { BestsellerFilters } from '../components/bestseller-filters'
import { BestsellerInsights } from '../components/bestseller-insights'
import { BestsellerScopeStatus, BestsellerSyncStatus } from '../components/bestseller-status-bars'
import { BestsellerTable } from '../components/bestseller-table'
import { bestsellerRolloutConfig, shopIsInBestsellerRollout } from '../config/bestseller-rollout'
import {
  useBestsellerAuthorizationQuery,
  useBestsellerListQuery,
  useBestsellerReauthorizationMutation,
  useBestsellerShopsQuery,
  useBestsellerSyncMutation,
} from '../queries/bestseller.queries'
import type {
  BestsellerAuthorType,
  BestsellerCurrency,
  BestsellerQuery,
  BestsellerRoute,
  BestsellerTimeSlot,
} from '../types/bestseller.types'
import { latestCompletedShopDate } from '../utils/shop-date'
import './bestsellers-page.css'

const routes: BestsellerRoute[] = ['products', 'creators', 'videos', 'lives']
const slots: BestsellerTimeSlot[] = ['1D', '7D', '30D']
const currencies: BestsellerCurrency[] = ['USD', 'LOCAL']
const authors: BestsellerAuthorType[] = ['ALL', 'OFFICIAL', 'CHANNEL', 'AFFILIATE']

function allowed<T extends string>(value: string | null, values: T[], fallback: T): T {
  return values.includes(value as T) ? (value as T) : fallback
}

export default function BestsellersPage() {
  const { hasPermissions } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [queuedCount, setQueuedCount] = useState(0)
  const shops = useBestsellerShopsQuery()
  const eligibleShops = useMemo(
    () => (shops.data ?? []).filter((shop) => shopIsInBestsellerRollout(shop, bestsellerRolloutConfig)),
    [shops.data],
  )
  const requestedShopId = searchParams.get('shopId') ?? undefined
  const shopId = eligibleShops.some((shop) => shop.id === requestedShopId) ? requestedShopId : eligibleShops[0]?.id
  const selectedShop = eligibleShops.find((shop) => shop.id === shopId)
  const maxDate = dayjs(latestCompletedShopDate(selectedShop?.timezone ?? null))
  const entity = allowed(searchParams.get('tab'), routes, 'products')
  const dateParam = searchParams.get('date')
  const requestedDate = dateParam && dayjs(dateParam).isValid() ? dayjs(dateParam) : maxDate
  const date = requestedDate.isAfter(maxDate, 'day') ? maxDate : requestedDate
  const timeSlot = allowed(searchParams.get('timeSlot'), slots, '7D')
  const currency = allowed(searchParams.get('currency'), currencies, 'USD')
  const authorType = allowed(searchParams.get('authorType'), authors, 'ALL')
  const authorization = useBestsellerAuthorizationQuery(shopId)
  const query = useMemo<BestsellerQuery>(
    () => ({
      shopId: shopId ?? '',
      date: date.format('YYYY-MM-DD'),
      timeSlot,
      currency,
      authorType: entity === 'creators' ? authorType : undefined,
    }),
    [authorType, currency, date, entity, shopId, timeSlot],
  )
  const canRead = authorization.data?.data.canRead === true
  const list = useBestsellerListQuery(query, entity, Boolean(shopId) && canRead, queuedCount > 0)
  const sync = useBestsellerSyncMutation()
  const reauthorization = useBestsellerReauthorizationMutation()

  useEffect(() => {
    if (!shopId) return
    const next = new URLSearchParams(searchParams)
    next.set('shopId', shopId)
    next.set('tab', entity)
    next.set('date', query.date)
    next.set('timeSlot', timeSlot)
    next.set('currency', currency)
    next.set('authorType', authorType)
    if (next.toString() !== searchParams.toString()) setSearchParams(next, { replace: true })
  }, [authorType, currency, entity, query.date, searchParams, setSearchParams, shopId, timeSlot])

  const update = (values: Record<string, string | undefined>) => {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setQueuedCount(0)
    setSearchParams(next, { replace: true })
  }
  const runSync = () => {
    if (!shopId) return
    sync.mutate(
      { ...query, entityTypes: [entity] },
      {
        onSuccess: (response) => {
          setQueuedCount(response.data.jobIds.length + response.data.alreadyQueued.length)
          window.setTimeout(() => setQueuedCount(0), 30_000)
          void list.refetch()
        },
      },
    )
  }

  if (shops.isLoading) return <PageLoading fullscreen />
  if (shops.isError)
    return <PageError description="店铺选择器需要 shops:view 权限。" onRetry={() => void shops.refetch()} />
  if (!shops.data?.length) return <PageError description="当前租户没有可用的 TikTok Shop 店铺。" />
  if (!eligibleShops.length) return <PageError description="畅销榜当前仅对指定灰度店铺开放；请检查灰度店铺配置。" />

  const canSync = Boolean(authorization.data?.data.canRead) && hasPermissions([modulePermissionCodes.syncTrigger])
  return (
    <Space className="bestsellers-page" orientation="vertical" size="large">
      <div className="bestsellers-page-header">
        <div>
          <Typography.Title level={2}>畅销榜</Typography.Title>
          <Typography.Text type="secondary">
            按结束日期与官方 1D / 7D / 30D 周期分析领先商品、创作者、视频和直播；GMV 仅展示脱敏区间。
          </Typography.Text>
        </div>
      </div>
      {isBestsellersMock && <Alert title="当前为畅销榜独立 Mock 模式" showIcon type="info" />}
      <Card className="bestseller-filter-card" size="small">
        <BestsellerFilters
          authorType={authorType}
          canSync={canSync}
          currency={currency}
          date={date}
          maxDate={maxDate}
          entity={entity}
          shopId={shopId}
          shops={eligibleShops}
          syncing={sync.isPending}
          timeSlot={timeSlot}
          onAuthorTypeChange={(value) => update({ authorType: value })}
          onCurrencyChange={(value) => update({ currency: value })}
          onDateChange={(value) => update({ date: value.format('YYYY-MM-DD') })}
          onRefresh={() => {
            void authorization.refetch()
            void list.refetch()
          }}
          onShopChange={(value) => update({ shopId: value })}
          onSync={runSync}
          onTimeSlotChange={(value) => update({ timeSlot: value })}
        />
      </Card>
      <BestsellerScopeStatus
        query={authorization}
        reauthorizing={reauthorization.isPending}
        onReauthorize={() => {
          if (!shopId) return
          reauthorization.mutate(shopId, {
            onSuccess: ({ authorizationUrl }) => window.location.assign(authorizationUrl),
          })
        }}
      />
      {reauthorization.isError && <Alert title="无法生成重新授权链接，请稍后重试。" showIcon type="error" />}
      {sync.isError && <Alert title="同步任务入队失败，请稍后重试。" showIcon type="error" />}
      <Card className="bestseller-ranking-card">
        <div className="bestseller-card-status">
          <BestsellerSyncStatus envelope={list.data} queuedCount={queuedCount} syncing={sync.isPending} />
        </div>
        <Tabs
          activeKey={entity}
          items={[
            { key: 'products', label: '商品榜' },
            { key: 'creators', label: '创作者榜' },
            { key: 'videos', label: '视频榜' },
            { key: 'lives', label: '直播榜' },
          ]}
          onChange={(value) => update({ tab: value })}
        />
        <BestsellerInsights entity={entity} entries={list.data?.data.items ?? []} />
        <BestsellerTable
          authorization={authorization}
          entity={entity}
          query={list}
          syncing={sync.isPending || queuedCount > 0}
        />
      </Card>
    </Space>
  )
}

import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Space, Tabs, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { AFFILIATE_REFRESH_INTERVAL_MS } from '../affiliate-refresh'
import { readAffiliateFilters, writeAffiliateFilterSearch } from '../affiliate-filter-query'
import { affiliateCenterApi } from '../api/affiliate-center.api'
import { AffiliateFilterBar, type AffiliateFilters } from '../components/affiliate-filter-bar'
import { CreatorDetailTable } from '../components/creator-detail-table'
import { AffiliateAvatar } from '../components/affiliate-avatar'
import type {
  AffiliateCreatorDetail,
  AffiliateCreatorDetailPage,
  AffiliateCreatorDetailResource,
  AffiliateShop,
} from '../types/affiliate-center.types'
import './affiliate-center-page.css'

const resources: Array<{ key: AffiliateCreatorDetailResource; label: string }> = [
  { key: 'video', label: '带货视频' },
  { key: 'live', label: '直播' },
  { key: 'product', label: '商品' },
  { key: 'product-card', label: '商品卡' },
]

export default function AffiliateCreatorDetailPage() {
  const { creatorId = '' } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const filters = useMemo(() => readAffiliateFilters(location.search, 'creators'), [location.search])
  const activeResource = (new URLSearchParams(location.search).get('detailTab') ??
    'video') as AffiliateCreatorDetailResource
  const [shops, setShops] = useState<AffiliateShop[]>([])
  const [detail, setDetail] = useState<AffiliateCreatorDetail>()
  const [data, setData] = useState<AffiliateCreatorDetailPage>()
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [shopsLoading, setShopsLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [reloadToken, setReloadToken] = useState(0)

  const writeFilters = useCallback(
    (next: AffiliateFilters) => {
      const search = writeAffiliateFilterSearch(location.search, 'creators', next, false)
      void navigate({ pathname: location.pathname, search: `?${search}` }, { replace: true })
    },
    [location.pathname, location.search, navigate],
  )

  useEffect(() => {
    let active = true
    affiliateCenterApi
      .listShops()
      .then((items) => {
        if (!active) return
        setShops(items)
        if (!filters.shopId && items[0]) {
          writeFilters({ ...filters, shopId: items[0].id, currency: items[0].currency ?? filters.currency })
        }
      })
      .catch(() => active && setError('店铺读取失败，未回退到 Mock。'))
      .finally(() => active && setShopsLoading(false))
    return () => {
      active = false
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const load = useCallback(
    async (nextPage: number) => {
      if (!creatorId || !filters.shopId) return
      setLoading(true)
      setError(undefined)
      try {
        const [profile, pageData] = await Promise.all([
          affiliateCenterApi.getCreatorDetail(creatorId, filters.shopId),
          affiliateCenterApi.listCreatorDetailResource(creatorId, activeResource, {
            ...filters,
            page: nextPage,
            pageSize: 50,
          }),
        ])
        setDetail(profile)
        setData(pageData)
        setPage(nextPage)
      } catch {
        setData(undefined)
        setError('达人详情真实数据读取失败，未回退到 Mock。请检查店铺、日期范围和登录采集会话。')
      } finally {
        setLoading(false)
      }
    },
    [activeResource, creatorId, filters],
  )

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(1), 0)
    return () => window.clearTimeout(timeout)
  }, [load, reloadToken])

  useEffect(() => {
    if (!creatorId || !filters.shopId) return
    const interval = window.setInterval(() => void load(page), AFFILIATE_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [creatorId, filters.shopId, load, page])

  const changeTab = (key: string) => {
    const params = new URLSearchParams(location.search)
    params.set('detailTab', key)
    void navigate({ pathname: location.pathname, search: `?${params.toString()}` })
  }
  const report = data?.report
  return (
    <Space className="affiliate-center-page" orientation="vertical" size="large">
      <div className="affiliate-center-header">
        <Space>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => void navigate({ pathname: '/affiliate-center/creators', search: location.search })}
          />
          <AffiliateAvatar alt={detail?.creator.username ?? 'Creator'} size={64} url={detail?.creator.avatarUrl}>
            {detail?.creator.username.slice(0, 1).toUpperCase()}
          </AffiliateAvatar>
          <div>
            <Typography.Title level={3}>{detail?.creator.username ?? '达人详情'}</Typography.Title>
            <Typography.Text type="secondary">
              {detail?.creator.creatorOpenId ? `Open ID · ${detail.creator.creatorOpenId}` : '平台达人身份'}
            </Typography.Text>
          </div>
        </Space>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => setReloadToken((value) => value + 1)}>
          刷新详情
        </Button>
      </div>
      <AffiliateFilterBar filters={filters} loading={shopsLoading} shops={shops} onChange={writeFilters} />
      <Tabs activeKey={activeResource} items={resources} onChange={changeTab} />
      {error && <Alert showIcon type="error" title={error} />}
      {!error && !loading && !report && (
        <Alert
          showIcon
          type="warning"
          title="当前查询窗口尚无详情快照。请在已登录的 TikTok 达人详情页保持该窗口，daemon 会自动采集四个页签。"
        />
      )}
      <Card>
        <CreatorDetailTable
          currency={filters.currency}
          items={data?.items ?? []}
          loading={loading}
          page={page}
          resource={activeResource}
          total={data?.total ?? 0}
          onPageChange={(nextPage) => void load(nextPage)}
        />
      </Card>
    </Space>
  )
}

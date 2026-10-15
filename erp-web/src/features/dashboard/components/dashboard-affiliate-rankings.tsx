import { useState } from 'react'
import { DownloadOutlined } from '@ant-design/icons'
import { Alert, Button, Select, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useDashboardAffiliateRankingsQuery } from '../queries/dashboard.queries'
import type {
  DashboardQueryParams,
  DashboardRankingDays,
  DashboardTopProduct,
  DashboardTopVideo,
} from '../types/dashboard.types'
import { formatMoney, formatNumber } from './dashboard-format'
import { downloadRankingCsv } from './dashboard-ranking-csv'

const daysOptions = [
  { value: 7, label: '近 7 天' },
  { value: 30, label: '近 30 天' },
  { value: 90, label: '近 90 天' },
]

function publishedDate(value: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString('zh-CN')
}

function RankingThumbnail({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false)
  return url && !failed ? (
    <img alt="" className="dashboard-rank-thumb" height={42} onError={() => setFailed(true)} src={url} width={42} />
  ) : (
    <span className="dashboard-rank-thumb-empty">无图</span>
  )
}

interface Props {
  params: DashboardQueryParams
}

export function DashboardAffiliateRankings({ params }: Props) {
  const [days, setDays] = useState<DashboardRankingDays>(7)
  const query = useDashboardAffiliateRankingsQuery(params, days)
  const data = query.isPlaceholderData ? undefined : query.data
  const loading = query.isFetching
  const period = data?.period ? `${data.period.start} 至 ${data.period.end}` : '暂无完整数据窗口'

  const videoColumns: ColumnsType<DashboardTopVideo> = [
    {
      title: '视频 / 达人',
      key: 'video',
      render: (_, row) => (
        <div className="dashboard-rank-entity">
          <RankingThumbnail url={row.coverImageUrl} />
          <div>
            <b title={row.title || row.videoId}>{row.title || row.videoId}</b>
            <small>{row.creatorUsername ? `@${row.creatorUsername.replace(/^@/, '')}` : row.shopName}</small>
          </div>
        </div>
      ),
    },
    {
      title: '视频 GMV',
      dataIndex: 'gmvMinor',
      align: 'right',
      width: 108,
      render: (value: number) => formatMoney(value, params.currency),
    },
    {
      title: '播放量',
      dataIndex: 'views',
      align: 'right',
      width: 92,
      render: (value: number | null) => (value == null ? '—' : formatNumber(value)),
    },
    { title: '发布时间', dataIndex: 'videoPostTime', align: 'right', width: 100, render: publishedDate },
  ]
  const productColumns: ColumnsType<DashboardTopProduct> = [
    {
      title: '商品',
      key: 'product',
      render: (_, row) => (
        <div className="dashboard-rank-entity">
          <RankingThumbnail url={row.coverImageUrl} />
          <div>
            <b title={row.title || row.productId}>{row.title || row.productId}</b>
            <small>商品 ID：{row.productId}</small>
          </div>
        </div>
      ),
    },
    { title: '视频数', dataIndex: 'videoCount', align: 'right', width: 80, render: formatNumber },
    {
      title: <Tooltip title="仅汇总只推广一个商品的视频 GMV；推广多个商品的视频不分摊">单品视频 GMV</Tooltip>,
      dataIndex: 'singleProductVideoGmvMinor',
      align: 'right',
      width: 132,
      render: (value: number | null) => (value == null ? '—' : formatMoney(value, params.currency)),
    },
    {
      title: <Tooltip title="仅汇总只推广一个商品的视频销量；多商品视频不分摊">单品视频销量</Tooltip>,
      dataIndex: 'singleProductVideoItemsSold',
      align: 'right',
      width: 88,
      render: (value: number | null) => (value == null ? '—' : formatNumber(value)),
    },
  ]

  const exportVideos = () => {
    if (!data) return
    downloadRankingCsv(
      `top-videos-${days}d.csv`,
      ['店铺', '视频 ID', '达人', '标题', '视频 GMV', '播放量', '发布时间'],
      data.topVideos.map((row) => [
        row.shopName,
        row.videoId,
        row.creatorUsername,
        row.title,
        row.gmvMinor / 100,
        row.views,
        row.videoPostTime,
      ]),
    )
  }
  const exportProducts = () => {
    if (!data) return
    downloadRankingCsv(
      `top-products-${days}d.csv`,
      ['店铺', '商品 ID', '商品', '关联视频数', '单品视频 GMV', '单品视频销量'],
      data.topProducts.map((row) => [
        row.shopName,
        row.productId,
        row.title,
        row.videoCount,
        row.singleProductVideoGmvMinor == null ? null : row.singleProductVideoGmvMinor / 100,
        row.singleProductVideoItemsSold,
      ]),
    )
  }

  return (
    <section className="dashboard-affiliate-rankings" aria-label="联盟视频与商品排行榜">
      {query.isError && (
        <Alert type="error" showIcon message="联盟排行榜加载失败" description="不影响下方商品业绩表现；请稍后重试。" />
      )}
      {data && !data.complete && (
        <Alert
          type="warning"
          showIcon
          message={`仅 ${data.shopCount}/${data.expectedShopCount} 家店铺有完整的 ${days} 天视频数据，以下为已覆盖店铺的榜单`}
        />
      )}
      <div className="dashboard-rank-grid">
        <article className="dashboard-panel dashboard-rank-panel">
          <div className="dashboard-rank-header">
            <div>
              <h2>
                Top Videos <span>{data?.totalVideos ?? 0}</span>
              </h2>
              <small>{period}</small>
            </div>
            <div className="dashboard-rank-actions">
              <Select aria-label="视频排行榜周期" options={daysOptions} value={days} onChange={setDays} size="small" />
              <Button
                icon={<DownloadOutlined />}
                onClick={exportVideos}
                disabled={!data?.topVideos.length}
                size="small"
              >
                导出 CSV
              </Button>
            </div>
          </div>
          <Table
            columns={videoColumns}
            dataSource={data?.topVideos ?? []}
            loading={loading}
            rowKey="id"
            locale={{ emptyText: '暂无完整周期的视频业绩数据' }}
            pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
            scroll={{ x: 570 }}
            size="small"
            tableLayout="fixed"
          />
        </article>
        <article className="dashboard-panel dashboard-rank-panel">
          <div className="dashboard-rank-header">
            <div>
              <h2>
                Top Products <span>{data?.totalProducts ?? 0}</span>
              </h2>
              <small>{period}</small>
            </div>
            <div className="dashboard-rank-actions">
              <Select aria-label="商品排行榜周期" options={daysOptions} value={days} onChange={setDays} size="small" />
              <Button
                icon={<DownloadOutlined />}
                onClick={exportProducts}
                disabled={!data?.topProducts.length}
                size="small"
              >
                导出 CSV
              </Button>
            </div>
          </div>
          <Table
            columns={productColumns}
            dataSource={data?.topProducts ?? []}
            loading={loading}
            rowKey="id"
            locale={{ emptyText: '暂无完整周期的联盟商品数据' }}
            pagination={{ pageSize: 10, showSizeChanger: false, hideOnSinglePage: true }}
            scroll={{ x: 570 }}
            size="small"
            tableLayout="fixed"
          />
        </article>
      </div>
      <p className="dashboard-rank-note">
        商品 GMV 与销量仅汇总单商品视频；多商品视频不分摊，不能视为商品完整联盟业绩。近 30/90
        天需完整视频快照。榜单最多展示及导出前 100 条。
      </p>
    </section>
  )
}

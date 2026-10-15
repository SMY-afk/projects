import { useMemo, useState } from 'react'
import { Avatar, Input, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type {
  DashboardAffiliateOperations,
  DashboardCreatorEfficiencyRow,
  DashboardParetoPoint,
} from '../types/dashboard.types'
import { formatMoney, formatNumber } from './dashboard-format'

interface DashboardAffiliateOperationsProps {
  data: DashboardAffiliateOperations
  currency: string
}

const sampleStatusLabels: Record<string, { label: string; color: string }> = {
  PENDING: { label: '待审核', color: 'gold' },
  AWAITING_SHIPMENT: { label: '待发货', color: 'orange' },
  SHIPPED: { label: '已发货', color: 'cyan' },
  CONTENT_PENDING: { label: '内容处理中', color: 'blue' },
  COMPLETED: { label: '已完成', color: 'green' },
  OPS_COMPLETED: { label: '已完成', color: 'green' },
  CANCELLED: { label: '已取消', color: 'red' },
  SELLER_NOT_SHIP_CANCELLED: { label: '卖家未发货取消', color: 'red' },
  CREATOR_NOT_SHIP_CANCELLED: { label: '达人未收货取消', color: 'red' },
}

function SampleFunnel({ data }: { data: DashboardAffiliateOperations['sampleFunnel'] }) {
  const stages = [
    { label: '样品申请', value: data.applicationCount, tone: 'orange' },
    { label: '审核通过', value: data.approvedCount, tone: 'amber' },
    { label: '已发货', value: data.shippedCount, tone: 'gold' },
    { label: '已完成', value: data.completedCount, tone: 'green' },
  ]
  const total = Math.max(data.applicationCount, 1)
  return (
    <article className="dashboard-panel sample-funnel-panel">
      <div className="dashboard-panel-title affiliate-panel-title">
        <div>
          <small>SAMPLE FUNNEL</small>
          <h2>样品状态漏斗</h2>
        </div>
        <span>当前全量 · 不受日期筛选影响</span>
      </div>
      <div className="sample-funnel-list">
        {stages.map((stage) => (
          <div className="sample-funnel-row" key={stage.label}>
            <div className="sample-funnel-label">
              <span>{stage.label}</span>
              <strong>{formatNumber(stage.value)}</strong>
            </div>
            <div className="sample-funnel-track">
              <i
                className={stage.tone}
                style={{ width: `${Math.max(stage.value ? 5 : 0, (stage.value / total) * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="sample-funnel-foot">
        <span>取消或超时</span>
        <b>{formatNumber(data.cancelledCount)}</b>
        <small>按当前有效投影中的平台状态统计</small>
      </div>
    </article>
  )
}

function CreatorLevels({ data }: { data: DashboardAffiliateOperations['creatorLevels'] }) {
  const max = Math.max(...data.map((item) => item.count), 1)
  const total = data.reduce((sum, item) => sum + item.count, 0)
  return (
    <article className="dashboard-panel creator-level-panel">
      <div className="dashboard-panel-title affiliate-panel-title">
        <div>
          <small>CREATOR LEVEL BREAKDOWN</small>
          <h2>L0–L7 达人等级分布</h2>
        </div>
        <span>已分级 {formatNumber(total)}</span>
      </div>
      <div className="creator-level-list">
        {data.map((item) => (
          <div className="creator-level-row" key={item.level}>
            <b data-level={item.level}>{item.level}</b>
            <div className="creator-level-track">
              <i style={{ width: `${(item.count / max) * 100}%` }} />
            </div>
            <strong>{formatNumber(item.count)}</strong>
            <span>{item.share.toFixed(1)}%</span>
          </div>
        ))}
      </div>
      <p className="creator-level-note">等级来自达人 GMV 分层；缺少可靠 GMV 的申请不会进入等级占比。</p>
    </article>
  )
}

function paretoPath(points: DashboardParetoPoint[], width: number, height: number) {
  return points
    .map((point, index) => {
      const x = ((index + 0.5) / Math.max(points.length, 1)) * width
      const y = height - (point.cumulativeGmvShare / 100) * height
      return `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function ParetoChart({ points, currency }: { points: DashboardParetoPoint[]; currency: string }) {
  const visible = points.slice(0, 12)
  const width = 900
  const height = 190
  const max = Math.max(...visible.map((point) => point.gmvMinor), 1)
  if (!visible.length) return <div className="affiliate-empty">所选周期暂无完整达人业绩数据</div>
  return (
    <div className="pareto-chart">
      <div className="pareto-legend">
        <span>
          <i />
          达人 GMV
        </span>
        <span>
          <i className="line" />
          累计贡献率
        </span>
      </div>
      <svg aria-label="达人GMV帕累托图" preserveAspectRatio="none" viewBox={`0 0 ${width} ${height}`}>
        {[0, 0.5, 1].map((ratio) => (
          <line className="pareto-gridline" key={ratio} x1="0" x2={width} y1={height * ratio} y2={height * ratio} />
        ))}
        {visible.map((point, index) => {
          const slot = width / visible.length
          const barHeight = (point.gmvMinor / max) * (height - 8)
          return (
            <rect
              className="pareto-bar"
              height={barHeight}
              key={point.id}
              rx="3"
              width={Math.max(8, slot * 0.56)}
              x={index * slot + slot * 0.22}
              y={height - barHeight}
            />
          )
        })}
        <path className="pareto-line" d={paretoPath(visible, width, height)} />
        {visible.map((point, index) => (
          <circle
            className="pareto-dot"
            cx={((index + 0.5) / visible.length) * width}
            cy={height - (point.cumulativeGmvShare / 100) * height}
            key={point.id}
            r="3"
          />
        ))}
      </svg>
      <div className="pareto-labels">
        {visible.map((point) => (
          <span key={point.id} title={`${point.username} · ${formatMoney(point.gmvMinor, currency)}`}>
            @{point.username.replace(/^@/, '')}
          </span>
        ))}
      </div>
    </div>
  )
}

function sampleStatus(value: string | null) {
  if (!value) return <Tag>无样品</Tag>
  const status = sampleStatusLabels[value]
  if (!status) return <Tag>{value}</Tag>
  return <Tag color={status.color}>{status.label}</Tag>
}

export function DashboardAffiliateOperations({ data, currency }: DashboardAffiliateOperationsProps) {
  const [search, setSearch] = useState('')
  const { creatorEfficiency } = data
  const rows = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) return creatorEfficiency.rows
    return creatorEfficiency.rows.filter((row) => `${row.username} ${row.shopName}`.toLowerCase().includes(keyword))
  }, [creatorEfficiency.rows, search])
  const columns: ColumnsType<DashboardCreatorEfficiencyRow> = [
    { title: '#', dataIndex: 'rank', width: 48, align: 'center' },
    {
      title: '达人',
      width: 190,
      render: (_, row) => (
        <div className="efficiency-creator">
          <Avatar size={30} src={row.avatarUrl}>
            {row.username.slice(0, 1).toUpperCase()}
          </Avatar>
          <span>
            <b>@{row.username.replace(/^@/, '')}</b>
            <small>{row.shopName}</small>
          </span>
        </div>
      ),
    },
    { title: '视频', dataIndex: 'videoCount', align: 'right', width: 72, render: formatNumber },
    {
      title: 'GMV',
      dataIndex: 'gmvMinor',
      align: 'right',
      width: 100,
      render: (value: number) => formatMoney(value, currency),
    },
    {
      title: 'GMV / 视频',
      dataIndex: 'gmvPerVideoMinor',
      align: 'right',
      width: 110,
      render: (value: number) => formatMoney(value, currency),
    },
    { title: '样品状态', dataIndex: 'sampleStatus', width: 100, render: sampleStatus },
  ]
  const period = creatorEfficiency.period
    ? `${creatorEfficiency.period.start} — ${creatorEfficiency.period.end}`
    : '暂无完整周期'
  return (
    <section className="dashboard-affiliate-operations">
      <div className="dashboard-affiliate-top">
        <SampleFunnel data={data.sampleFunnel} />
        <CreatorLevels data={data.creatorLevels} />
      </div>
      <article className="dashboard-panel creator-efficiency-panel">
        <div className="dashboard-panel-title affiliate-panel-title">
          <div>
            <small>CREATOR EFFICIENCY</small>
            <h2>达人效率与 GMV Pareto</h2>
          </div>
          <div className="creator-efficiency-actions">
            <span>
              {period}
              {creatorEfficiency.complete ? '' : ' · 数据不完整'}
            </span>
            <Input
              allowClear
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索达人或店铺"
              size="small"
              value={search}
            />
          </div>
        </div>
        <div className="creator-efficiency-summary">
          <span>
            达人 <b>{formatNumber(creatorEfficiency.totalCreators)}</b>
          </span>
          <span>
            联盟 GMV <b>{formatMoney(creatorEfficiency.totalGmvMinor, currency)}</b>
          </span>
          <span>
            覆盖店铺 <b>{creatorEfficiency.shopCount}</b>
          </span>
        </div>
        <div className="creator-efficiency-layout">
          <ParetoChart currency={currency} points={creatorEfficiency.pareto} />
          <Table
            columns={columns}
            dataSource={rows}
            locale={{ emptyText: '当前筛选条件暂无达人业绩数据' }}
            pagination={{ pageSize: 8, hideOnSinglePage: true, showSizeChanger: false }}
            rowKey="id"
            scroll={{ x: 620 }}
            size="small"
          />
        </div>
      </article>
    </section>
  )
}

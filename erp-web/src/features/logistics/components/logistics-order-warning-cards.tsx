import { Button, Card } from 'antd'
import type { LogisticsAlertPhase, LogisticsOrderAlert, LogisticsWarnings } from '../types/logistics-status.types'
import { overdueDuration, warningLabels } from '../utils/logistics-warning-presentation'

export function LogisticsOrderWarningCards({ warnings, selected, phase, onSelect }: {
  warnings?: LogisticsWarnings | null
  selected?: LogisticsOrderAlert
  phase?: LogisticsAlertPhase
  onSelect: (key: LogisticsOrderAlert, phase: LogisticsAlertPhase) => void
}) {
  return <div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16 }}>
      {(Object.keys(warningLabels) as LogisticsOrderAlert[]).map((key) => {
        const card = warnings?.cards.find((item) => item.key === key)
        return <Card key={key} size="small" title={warningLabels[key]}>
          <div style={{ display: 'flex', gap: 8 }}>
            {(['upcoming', 'overdue'] as const).map((level) => {
              const count = level === 'upcoming' ? card?.upcomingCount : card?.overdueCount
              const label = level === 'upcoming' ? '快超时订单' : '已超时订单'
              const active = selected === key && phase === level
              return <Button key={level} disabled={!warnings} aria-pressed={active}
                aria-label={`${warningLabels[key]}：${label}`} onClick={() => onSelect(key, level)}
                style={{ flex: 1, height: 'auto', padding: '12px 8px', whiteSpace: 'normal',
                  color: level === 'upcoming' ? '#ad6800' : '#cf1322',
                  background: level === 'upcoming' ? '#fffbe6' : '#fff1f0',
                  borderColor: active ? '#167d76' : level === 'upcoming' ? '#ffe58f' : '#ffa39e' }}>
                <div>{label}</div><strong style={{ fontSize: 24 }}>{count ?? '—'}</strong> 单
              </Button>
            })}
          </div>
          <div style={{ marginTop: 8 }}>最近截止：{card?.upcomingCount ? `剩余${overdueDuration(card.closestRemainingSeconds)}` : '无快超时订单'}</div>
          <div>最长超时：{card?.overdueCount ? overdueDuration(card.longestOverdueSeconds) : '无超时'}</div>
        </Card>
      })}
    </div>
  </div>
}

import { Button, InputNumber, Space, Typography, message } from 'antd'
import { useState } from 'react'
import { useAuth } from '@/auth/use-auth'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { logisticsStatusApi } from '../api/logistics-status.api'

export function LogisticsAlertSettings({ hours, onSaved }: { hours: number; onSaved: () => Promise<unknown> }) {
  const { hasPermissions } = useAuth()
  const canManage = hasPermissions([modulePermissionCodes.logisticsManage])
  const [draft, setDraft] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const save = async () => {
    setSaving(true)
    try {
      await logisticsStatusApi.updateAlertSettings(draft ?? hours)
      await onSaved()
      setDraft(null)
      void message.success('提前预警时间已保存，三个节点使用同一设置')
    } catch {
      void message.error('提前预警时间保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }
  return <Space wrap>
    <Typography.Text>提前预警时间：</Typography.Text>
    {canManage ? <>
      <InputNumber aria-label="提前预警小时数" min={0.1} max={47.9} step={0.5} precision={1}
        value={draft ?? hours} onChange={setDraft} suffix="小时" disabled={saving} />
      <Button loading={saving} disabled={draft === null || draft === hours} onClick={() => void save()}>保存预警设置</Button>
    </> : <Typography.Text>{hours} 小时</Typography.Text>}
    <Typography.Text type="secondary">从订单创建时间起算，截止时长保持 48／48／77 小时</Typography.Text>
  </Space>
}

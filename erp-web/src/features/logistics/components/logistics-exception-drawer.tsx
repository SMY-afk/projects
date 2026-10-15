import { Button, Descriptions, Drawer, Input, Modal, Select, Space, Tag, Timeline, Typography } from 'antd'
import { useState } from 'react'
import type { LogisticsException, LogisticsExceptionActionRequest } from '../types/logistics-exception.types'
import {
  exceptionActionLabels,
  exceptionSeverityPresentation,
  exceptionStatusPresentation,
  exceptionTypeLabels,
} from './logistics-exception-presentation'

type ActionName = 'note' | 'escalate' | 'resolve' | 'close'

interface Props {
  record: LogisticsException | undefined
  open: boolean
  loading: boolean
  canOperate: boolean
  canManage: boolean
  actionLoading: boolean
  onClose: () => void
  onAction: (action: 'claim' | ActionName, values: LogisticsExceptionActionRequest) => Promise<void>
}

const actionTitles: Record<ActionName, string> = {
  note: '添加处理备注',
  escalate: '升级异常',
  resolve: '解决异常',
  close: '关闭异常',
}

export function LogisticsExceptionDrawer(props: Props) {
  const { record } = props
  const [action, setAction] = useState<ActionName | null>(null)
  const [text, setText] = useState('')
  const [severity, setSeverity] = useState<'high' | 'critical'>('high')
  const submit = async () => {
    if (!record || !action) return
    await props.onAction(action, {
      exceptionId: record.id,
      versionId: record.versionId,
      note: action === 'resolve' ? undefined : text,
      resolution: action === 'resolve' ? text : undefined,
      severity: action === 'escalate' ? severity : undefined,
    })
    setAction(null)
    setText('')
  }
  const runClaim = () => record && props.onAction('claim', { exceptionId: record.id, versionId: record.versionId })

  return (
    <>
      <Drawer
        loading={props.loading}
        onClose={props.onClose}
        open={props.open}
        title={record?.exceptionNumber}
        width={680}
      >
        {record && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions bordered column={2} size="small">
              <Descriptions.Item label="异常类型">{exceptionTypeLabels[record.exceptionType]}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={exceptionStatusPresentation[record.status].color}>
                  {exceptionStatusPresentation[record.status].label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="级别">
                <Tag color={exceptionSeverityPresentation[record.severity].color}>
                  {exceptionSeverityPresentation[record.severity].label}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="累计识别">{record.occurrenceCount} 次</Descriptions.Item>
              <Descriptions.Item label="物流任务">{record.taskNumber}</Descriptions.Item>
              <Descriptions.Item label="来源订单">{record.sourceNumber}</Descriptions.Item>
              <Descriptions.Item label="物流商">{record.carrierName}</Descriptions.Item>
              <Descriptions.Item label="运单号">{record.trackingNumberMasked ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="异常说明" span={2}>
                {record.description}
              </Descriptions.Item>
              {record.resolution && (
                <Descriptions.Item label="解决结果" span={2}>
                  {record.resolution}
                </Descriptions.Item>
              )}
            </Descriptions>
            <Space wrap>
              {props.canOperate && record.status === 'open' && (
                <Button type="primary" onClick={() => void runClaim()}>
                  认领
                </Button>
              )}
              {props.canOperate && record.status !== 'closed' && (
                <Button onClick={() => setAction('note')}>备注</Button>
              )}
              {props.canManage && ['open', 'claimed'].includes(record.status) && (
                <Button danger onClick={() => setAction('escalate')}>
                  升级
                </Button>
              )}
              {props.canOperate && ['claimed', 'escalated'].includes(record.status) && (
                <Button type="primary" onClick={() => setAction('resolve')}>
                  解决
                </Button>
              )}
              {props.canManage && record.status === 'resolved' && (
                <Button onClick={() => setAction('close')}>关闭</Button>
              )}
            </Space>
            <div>
              <Typography.Title level={5}>处理记录</Typography.Title>
              <Timeline
                items={record.actions.map((item) => ({
                  children: (
                    <div>
                      <div>{exceptionActionLabels[item.actionType] ?? item.actionType}</div>
                      {item.note && <Typography.Text type="secondary">{item.note}</Typography.Text>}
                      <div>
                        <Typography.Text type="secondary">{new Date(item.createdAt).toLocaleString()}</Typography.Text>
                      </div>
                    </div>
                  ),
                }))}
              />
            </div>
          </Space>
        )}
      </Drawer>
      <Modal
        confirmLoading={props.actionLoading}
        okButtonProps={{ disabled: !text.trim() && action !== 'close' }}
        onCancel={() => setAction(null)}
        onOk={() => void submit()}
        open={Boolean(action)}
        title={action ? actionTitles[action] : ''}
      >
        {action === 'escalate' && (
          <Select
            onChange={setSeverity}
            options={[
              { label: '高', value: 'high' },
              { label: '紧急', value: 'critical' },
            ]}
            style={{ marginBottom: 12, width: '100%' }}
            value={severity}
          />
        )}
        <Input.TextArea
          maxLength={4000}
          onChange={(event) => setText(event.target.value)}
          placeholder={action === 'resolve' ? '填写解决结果' : '填写处理说明'}
          rows={4}
          value={text}
        />
      </Modal>
    </>
  )
}

import { ArrowLeftOutlined, BarcodeOutlined } from '@ant-design/icons'
import { App, Button, Card, Input, InputNumber, Result, Select, Space, Spin, Table, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { logisticsApi } from '../api/logistics.api'
import { LogisticsStatusSteps } from '../components/logistics-status-steps'
import { useLogisticsTaskQuery, useReviewTaskMutation } from '../queries/logistics.queries'
import type { LogisticsDifferenceReason, LogisticsTaskItem } from '../types/logistics.types'
import './logistics-page.css'

const reasonOptions = [
  { label: '短少', value: 'shortage' },
  { label: '多出', value: 'overage' },
  { label: '破损', value: 'damaged' },
  { label: 'SKU 错误', value: 'wrong_sku' },
  { label: '其他', value: 'other' },
] satisfies Array<{ label: string; value: LogisticsDifferenceReason }>

export default function LogisticsReviewPage() {
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const taskQuery = useLogisticsTaskQuery(taskId)
  const mutation = useReviewTaskMutation(taskId)
  const [actualQuantities, setActualQuantities] = useState<Record<string, number>>({})
  const [reasons, setReasons] = useState<Record<string, LogisticsDifferenceReason | undefined>>({})
  const [scanCode, setScanCode] = useState('')
  const [scanning, setScanning] = useState(false)
  const [note, setNote] = useState('')

  if (taskQuery.isLoading) return <Spin />
  if (taskQuery.isError || !taskQuery.data) return <Result status="error" title="复核任务加载失败" />
  const task = taskQuery.data
  const pickingCompleted = task.operations.some((item) => item.operationType === 'picking_completed')
  const expectedQuantity = task.items.reduce((total, item) => total + item.plannedQuantity, 0)
  const actualQuantity = task.items.reduce((total, item) => total + (actualQuantities[item.id] ?? 0), 0)

  const scan = async () => {
    const code = scanCode.trim()
    if (!code) return
    setScanning(true)
    try {
      const result = await logisticsApi.resolveScan(code, taskId)
      if (result.matchType === 'task') {
        void message.success('订单号与当前物流任务匹配')
      } else if (result.items.length === 1) {
        const item = result.items[0]
        setActualQuantities((current) => ({ ...current, [item.taskItemId]: (current[item.taskItemId] ?? 0) + 1 }))
        void message.success(`${item.sellerSku ?? item.platformSkuId ?? item.productName} 已累计 1 件`)
      } else if (result.items.length > 1) {
        void message.warning('该 SKU 对应多个任务明细，请手工选择并填写数量')
      } else {
        void message.warning('未在当前物流任务中找到该订单号或 SKU')
      }
      setScanCode('')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '扫码解析失败')
    } finally {
      setScanning(false)
    }
  }

  const submit = async () => {
    const missingReason = task.items.some((item) => {
      const actual = actualQuantities[item.id] ?? 0
      return actual !== item.plannedQuantity && !reasons[item.id]
    })
    if (missingReason) {
      void message.warning('数量不一致的商品必须选择差异原因')
      return
    }
    try {
      await mutation.mutateAsync({
        items: task.items.map((item) => ({
          taskItemId: item.id,
          actualQuantity: actualQuantities[item.id] ?? 0,
          differenceReason:
            (actualQuantities[item.id] ?? 0) === item.plannedQuantity ? null : (reasons[item.id] ?? null),
        })),
        note: note.trim() || null,
      })
      void message.success('订单复核已保存')
      void navigate(`/logistics/tasks/${taskId}`)
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '订单复核保存失败')
    }
  }

  if (!pickingCompleted) {
    return (
      <Result
        status="warning"
        title="请先确认配货完成"
        extra={<Button onClick={() => void navigate(`/logistics/tasks/${taskId}`)}>返回任务详情</Button>}
      />
    )
  }

  return (
    <Space className="logistics-page" orientation="vertical" size="large">
      <Button icon={<ArrowLeftOutlined />} onClick={() => void navigate(`/logistics/tasks/${taskId}`)}>
        返回任务详情
      </Button>
      <Typography.Title level={3}>订单复核 · {task.taskNumber}</Typography.Title>
      <Card title="当前状态">
        <LogisticsStatusSteps status={task.status} />
      </Card>
      <Card title="扫描订单号或 SKU">
        <Input
          autoFocus
          onChange={(event) => setScanCode(event.target.value)}
          onPressEnter={() => void scan()}
          placeholder="扫描后按回车；不扫描库位"
          prefix={<BarcodeOutlined />}
          suffix={
            <Button loading={scanning} onClick={() => void scan()}>
              识别
            </Button>
          }
          value={scanCode}
        />
      </Card>
      <Card title="逐项复核">
        <Table<LogisticsTaskItem>
          dataSource={task.items}
          pagination={false}
          rowKey="id"
          columns={[
            { title: '商品', dataIndex: 'productName' },
            { title: 'SKU', dataIndex: 'sellerSku', render: (value: string | null) => value ?? '-' },
            { title: '应复核数量', dataIndex: 'plannedQuantity' },
            {
              title: '实盘数量',
              render: (_: unknown, item: LogisticsTaskItem) => (
                <InputNumber
                  min={0}
                  precision={0}
                  value={actualQuantities[item.id] ?? 0}
                  onChange={(value) => setActualQuantities((current) => ({ ...current, [item.id]: value ?? 0 }))}
                />
              ),
            },
            {
              title: '差异原因',
              render: (_: unknown, item: LogisticsTaskItem) => {
                const matches = (actualQuantities[item.id] ?? 0) === item.plannedQuantity
                return (
                  <Select
                    allowClear
                    disabled={matches}
                    onChange={(value) => setReasons((current) => ({ ...current, [item.id]: value }))}
                    options={reasonOptions}
                    placeholder={matches ? '无差异' : '请选择'}
                    value={matches ? undefined : reasons[item.id]}
                    style={{ width: 130 }}
                  />
                )
              },
            },
          ]}
        />
        <Typography.Paragraph>
          应复核 {expectedQuantity} 件，实盘 {actualQuantity} 件
        </Typography.Paragraph>
        <Input.TextArea
          maxLength={2000}
          placeholder="差异、破损或数量不一致的补充说明"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <Button loading={mutation.isPending} onClick={() => void submit()} type="primary">
          提交复核
        </Button>
      </Card>
    </Space>
  )
}

import { ArrowLeftOutlined } from '@ant-design/icons'
import { Button, Card, Result, Space, Spin, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { LogisticsShippingPanel } from '../components/logistics-shipping-panel'
import { useLogisticsPackagesQuery, useLogisticsTaskQuery } from '../queries/logistics.queries'
import './logistics-page.css'

export default function LogisticsShippingPage() {
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const taskQuery = useLogisticsTaskQuery(taskId)
  const packagesQuery = useLogisticsPackagesQuery(taskId)
  const [selectedId, setSelectedId] = useState('')
  const packages = (packagesQuery.data ?? []).filter((item) => ['packed', 'waybill_created'].includes(item.status))
  const selected = packages.find((item) => item.id === selectedId) ?? packages[0]

  if (taskQuery.isLoading || packagesQuery.isLoading) return <Spin />
  if (taskQuery.isError || !taskQuery.data) return <Result status="error" title="运单数据加载失败" />

  return (
    <Space className="logistics-page" orientation="vertical" size="large">
      <Button icon={<ArrowLeftOutlined />} onClick={() => void navigate(`/logistics/tasks/${taskId}`)}>
        返回任务详情
      </Button>
      <Typography.Title level={3}>物流服务与运单 · {taskQuery.data.taskNumber}</Typography.Title>
      <div className="logistics-shipping-grid">
        <Card title="待处理包裹">
          <Space orientation="vertical" style={{ width: '100%' }}>
            {packages.map((item) => (
              <Button
                block
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                type={item.id === selected?.id ? 'primary' : 'default'}
              >
                {item.packageNumber} · {item.status === 'packed' ? '待运单' : '已建运单'}
              </Button>
            ))}
            {!packages.length && <Typography.Text type="secondary">暂无已封箱包裹</Typography.Text>}
          </Space>
        </Card>
        <Card title={selected ? `${selected.packageNumber} · 运单面板` : '请选择包裹'}>
          {selected ? (
            <LogisticsShippingPanel
              key={selected.id}
              packageItem={selected}
              taskId={taskId}
              taskItems={taskQuery.data.items}
            />
          ) : (
            <Result status="info" title="没有可处理包裹" />
          )}
        </Card>
      </div>
    </Space>
  )
}

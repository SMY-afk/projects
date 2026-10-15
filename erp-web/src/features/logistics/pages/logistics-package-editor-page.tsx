import { ArrowLeftOutlined, PlusOutlined } from '@ant-design/icons'
import { App, Button, Card, Result, Space, Spin, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { LogisticsPackageForm } from '../components/logistics-package-form'
import {
  useCreatePackageMutation,
  useLogisticsPackagesQuery,
  useLogisticsTaskQuery,
} from '../queries/logistics.queries'
import './logistics-page.css'

export default function LogisticsPackageEditorPage() {
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const taskQuery = useLogisticsTaskQuery(taskId)
  const packagesQuery = useLogisticsPackagesQuery(taskId)
  const createMutation = useCreatePackageMutation(taskId)
  const [selectedId, setSelectedId] = useState('')
  const packages = packagesQuery.data ?? []
  const selected = packages.find((item) => item.id === selectedId) ?? packages[0]

  if (taskQuery.isLoading || packagesQuery.isLoading) return <Spin />
  if (taskQuery.isError || !taskQuery.data) return <Result status="error" title="打包数据加载失败" />
  const task = taskQuery.data

  const createDraft = async () => {
    try {
      const created = await createMutation.mutateAsync({ note: null })
      setSelectedId(created.id)
      void message.success('已新增草稿包裹')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '新增包裹失败')
    }
  }

  return (
    <Space className="logistics-page" orientation="vertical" size="large">
      <Button icon={<ArrowLeftOutlined />} onClick={() => void navigate(`/logistics/tasks/${taskId}`)}>
        返回任务详情
      </Button>
      <div className="logistics-title-actions">
        <Typography.Title level={3}>打包面板 · {task.taskNumber}</Typography.Title>
        <Button
          icon={<PlusOutlined />}
          loading={createMutation.isPending}
          onClick={() => void createDraft()}
          type="primary"
        >
          新增包裹
        </Button>
      </div>
      <Space align="start" size="large" style={{ width: '100%' }}>
        <Card className="logistics-package-list" title="包裹列表">
          <Space orientation="vertical" style={{ width: '100%' }}>
            {packages.map((item) => (
              <Button
                block
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                type={item.id === selected?.id ? 'primary' : 'default'}
              >
                {item.packageNumber} ·{' '}
                {item.status === 'draft' ? '草稿' : item.status === 'packed' ? '已封箱' : item.status}
              </Button>
            ))}
            {!packages.length && <Typography.Text type="secondary">请先新增包裹</Typography.Text>}
          </Space>
        </Card>
        <Card style={{ flex: 1 }} title={selected ? `${selected.packageNumber} · 商品与尺寸` : '包裹内容'}>
          {selected ? (
            <LogisticsPackageForm key={`${selected.id}-${selected.versionId}`} packageItem={selected} task={task} />
          ) : (
            <Result status="info" title="请选择或新增包裹" />
          )}
        </Card>
      </Space>
    </Space>
  )
}

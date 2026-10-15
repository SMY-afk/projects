import { SaveOutlined } from '@ant-design/icons'
import { App, Button, Form, Input, InputNumber, Space, Table, Tag } from 'antd'
import { useState } from 'react'
import { useSealPackageMutation, useUpdatePackageMutation } from '../queries/logistics.queries'
import type {
  LogisticsPackage,
  LogisticsPackageDraftUpdateRequest,
  LogisticsTask,
  LogisticsTaskItem,
} from '../types/logistics.types'

type PackageFields = Omit<LogisticsPackageDraftUpdateRequest, 'versionId' | 'items'>

export function LogisticsPackageForm({ task, packageItem }: { task: LogisticsTask; packageItem: LogisticsPackage }) {
  const { message } = App.useApp()
  const [quantities, setQuantities] = useState<Record<string, number>>(
    Object.fromEntries(packageItem.items.map((item) => [item.taskItemId, item.quantity])),
  )
  const updateMutation = useUpdatePackageMutation(task.id, packageItem.id)
  const sealingMutation = useSealPackageMutation(task.id, packageItem.id, packageItem.status === 'packed')
  const editable = packageItem.status === 'draft'

  const saveDraft = async (values: PackageFields) => {
    const items = task.items
      .map((item) => ({ taskItemId: item.id, quantity: quantities[item.id] ?? 0 }))
      .filter((item) => item.quantity > 0)
    if (!items.length) {
      void message.warning('请至少向包裹分配一件商品')
      return
    }
    try {
      await updateMutation.mutateAsync({
        versionId: packageItem.versionId,
        items,
        weightGrams: values.weightGrams ?? null,
        lengthMm: values.lengthMm ?? null,
        widthMm: values.widthMm ?? null,
        heightMm: values.heightMm ?? null,
        note: values.note?.trim() || null,
      })
      void message.success('包裹草稿已保存')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '保存包裹草稿失败')
    }
  }

  const changeSealing = async () => {
    try {
      await sealingMutation.mutateAsync(packageItem.versionId)
      void message.success(editable ? '包裹已封箱' : '已撤销封箱')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '包裹状态更新失败')
    }
  }

  return (
    <Form<PackageFields>
      initialValues={{
        weightGrams: packageItem.weightGrams,
        lengthMm: packageItem.lengthMm,
        widthMm: packageItem.widthMm,
        heightMm: packageItem.heightMm,
        note: packageItem.note,
      }}
      layout="vertical"
      onFinish={(values) => void saveDraft(values)}
    >
      <Tag color={editable ? 'default' : 'green'}>{editable ? '草稿' : '已封箱'}</Tag>
      <Table<LogisticsTaskItem>
        dataSource={task.items}
        pagination={false}
        rowKey="id"
        columns={[
          { title: '商品', dataIndex: 'productName' },
          { title: 'SKU', dataIndex: 'sellerSku', render: (value: string | null) => value ?? '-' },
          { title: '计划', dataIndex: 'plannedQuantity' },
          { title: '已封箱', dataIndex: 'packedQuantity' },
          {
            title: '分配到本包裹',
            render: (_, item) => (
              <InputNumber
                disabled={!editable}
                max={item.plannedQuantity - item.packedQuantity}
                min={0}
                precision={0}
                value={quantities[item.id] ?? 0}
                onChange={(value) => setQuantities((current) => ({ ...current, [item.id]: value ?? 0 }))}
              />
            ),
          },
        ]}
      />
      <Space wrap>
        <Form.Item label="重量（克）" name="weightGrams">
          <InputNumber disabled={!editable} min={1} />
        </Form.Item>
        <Form.Item label="长（毫米）" name="lengthMm">
          <InputNumber disabled={!editable} min={1} />
        </Form.Item>
        <Form.Item label="宽（毫米）" name="widthMm">
          <InputNumber disabled={!editable} min={1} />
        </Form.Item>
        <Form.Item label="高（毫米）" name="heightMm">
          <InputNumber disabled={!editable} min={1} />
        </Form.Item>
      </Space>
      <Form.Item label="备注" name="note">
        <Input.TextArea disabled={!editable} maxLength={2000} />
      </Form.Item>
      <Space>
        {editable && (
          <Button htmlType="submit" icon={<SaveOutlined />} loading={updateMutation.isPending}>
            保存草稿
          </Button>
        )}
        {['draft', 'packed'].includes(packageItem.status) && (
          <Button
            danger={!editable}
            loading={sealingMutation.isPending}
            onClick={() => void changeSealing()}
            type="primary"
          >
            {editable ? '封箱' : '撤销封箱'}
          </Button>
        )}
      </Space>
    </Form>
  )
}

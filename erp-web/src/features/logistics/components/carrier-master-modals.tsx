import { App, Form, Input, Modal, Select } from 'antd'
import {
  useCreateCarrierMutation,
  useCreateCarrierServiceMutation,
  useCreatePlatformCarrierMappingMutation,
  useLogisticsShopOptionsQuery,
} from '../queries/logistics.queries'
import type { LogisticsCarrier } from '../types/logistics.types'

interface ModalProps {
  open: boolean
  onClose: () => void
}

interface CarrierTargetProps extends ModalProps {
  carrier: LogisticsCarrier | null
}

export function CarrierCreateModal({ open, onClose }: ModalProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const mutation = useCreateCarrierMutation()
  const submit = async (values: Record<string, string>) => {
    try {
      await mutation.mutateAsync({
        code: values.code,
        name: values.name,
        adapterKey: 'manual',
        trackingUrlTemplate: values.trackingUrlTemplate || null,
      })
      void message.success('承运商已创建')
      form.resetFields()
      onClose()
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '创建承运商失败')
    }
  }
  return (
    <Modal
      title="新增承运商"
      open={open}
      confirmLoading={mutation.isPending}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={(values: Record<string, string>) => void submit(values)}>
        <Form.Item label="承运商编码" name="code" rules={[{ required: true }]}>
          <Input placeholder="例如 UPS" />
        </Form.Item>
        <Form.Item label="承运商名称" name="name" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item label="轨迹查询 URL 模板" name="trackingUrlTemplate">
          <Input placeholder="可选，使用 {tracking_number} 作为占位符" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export function CarrierServiceCreateModal({ carrier, open, onClose }: CarrierTargetProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const mutation = useCreateCarrierServiceMutation(carrier?.id ?? '')
  const submit = async (values: Record<string, string>) => {
    if (!carrier) return
    try {
      await mutation.mutateAsync({
        code: values.code,
        name: values.name,
        serviceLevel: values.serviceLevel || null,
        supportedCountries: splitCodes(values.supportedCountries),
        platformProviderIds: {},
        trackingStatusMap: {},
      })
      void message.success('物流服务已创建')
      form.resetFields()
      onClose()
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '创建物流服务失败')
    }
  }
  return (
    <Modal
      title={`新增物流服务 · ${carrier?.name ?? ''}`}
      open={open}
      confirmLoading={mutation.isPending}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form form={form} layout="vertical" onFinish={(values: Record<string, string>) => void submit(values)}>
        <Form.Item label="服务编码" name="code" rules={[{ required: true }]}>
          <Input placeholder="例如 STANDARD" />
        </Form.Item>
        <Form.Item label="服务名称" name="name" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item label="服务等级" name="serviceLevel">
          <Input placeholder="standard / express" />
        </Form.Item>
        <Form.Item label="支持国家/地区" name="supportedCountries">
          <Input placeholder="US, GB, DE" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export function PlatformMappingCreateModal({ carrier, open, onClose }: CarrierTargetProps) {
  const [form] = Form.useForm()
  const { message } = App.useApp()
  const mutation = useCreatePlatformCarrierMappingMutation(carrier?.id ?? '')
  const shopsQuery = useLogisticsShopOptionsQuery()
  const submit = async (values: Record<string, string>) => {
    if (!carrier) return
    try {
      await mutation.mutateAsync({
        storeId: values.storeId,
        platform: values.platform,
        region: values.region,
        serviceId: values.serviceId || null,
        platformCarrierId: values.platformCarrierId,
        platformCarrierCode: values.platformCarrierCode || null,
        platformCarrierName: values.platformCarrierName || null,
        deliveryOptionId: values.deliveryOptionId || null,
      })
      void message.success('平台承运商映射已创建')
      form.resetFields()
      onClose()
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '创建平台映射失败')
    }
  }
  return (
    <Modal
      title={`新增平台映射 · ${carrier?.name ?? ''}`}
      open={open}
      confirmLoading={mutation.isPending}
      onCancel={onClose}
      onOk={() => form.submit()}
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{ platform: 'tiktok', region: 'GLOBAL' }}
        onFinish={(values: Record<string, string>) => void submit(values)}
      >
        <Form.Item label="平台" name="platform" rules={[{ required: true }]}>
          <Select options={[{ label: 'TikTok Shop', value: 'tiktok' }]} />
        </Form.Item>
        <Form.Item label="店铺" name="storeId" rules={[{ required: true }]}>
          <Select
            loading={shopsQuery.isLoading}
            options={(shopsQuery.data ?? []).map((shop) => ({
              label: shop.shopName,
              value: shop.id,
            }))}
          />
        </Form.Item>
        <Form.Item label="适用地区" name="region" rules={[{ required: true }]}>
          <Input placeholder="GLOBAL 或 US / GB / DE" />
        </Form.Item>
        <Form.Item label="限定物流服务" name="serviceId">
          <Select
            allowClear
            placeholder="不选则承运商下全部服务生效"
            options={(carrier?.services ?? []).map((item) => ({ label: item.name, value: item.id }))}
          />
        </Form.Item>
        <Form.Item label="平台承运商 ID" name="platformCarrierId" rules={[{ required: true }]}>
          <Input placeholder="shipping_provider_id" />
        </Form.Item>
        <Form.Item label="平台承运商编码" name="platformCarrierCode">
          <Input />
        </Form.Item>
        <Form.Item label="平台承运商名称" name="platformCarrierName">
          <Input />
        </Form.Item>
        <Form.Item label="配送选项 ID" name="deliveryOptionId">
          <Input />
        </Form.Item>
      </Form>
    </Modal>
  )
}

function splitCodes(value?: string) {
  return (value ?? '')
    .split(',')
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean)
}

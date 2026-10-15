import { PlusOutlined } from '@ant-design/icons'
import { App, Button, Card, Empty, Space, Switch, Table, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import {
  CarrierCreateModal,
  CarrierServiceCreateModal,
  PlatformMappingCreateModal,
} from '../components/carrier-master-modals'
import { LogisticsSectionNav } from '../components/logistics-section-nav'
import {
  useLogisticsCarriersQuery,
  useLogisticsShopOptionsQuery,
  useUpdatePlatformCarrierMappingMutation,
} from '../queries/logistics.queries'
import type {
  LogisticsCarrier,
  LogisticsCarrierService,
  LogisticsPlatformCarrierMapping,
} from '../types/logistics.types'

export default function LogisticsCarriersPage() {
  const { message } = App.useApp()
  const query = useLogisticsCarriersQuery()
  const shopsQuery = useLogisticsShopOptionsQuery()
  const updateMapping = useUpdatePlatformCarrierMappingMutation()
  const [carrierModal, setCarrierModal] = useState(false)
  const [serviceCarrier, setServiceCarrier] = useState<LogisticsCarrier | null>(null)
  const [mappingCarrier, setMappingCarrier] = useState<LogisticsCarrier | null>(null)
  const carriers = useMemo(() => query.data ?? [], [query.data])
  const shopNames = useMemo(
    () => new Map((shopsQuery.data ?? []).map((shop) => [shop.id, shop.shopName])),
    [shopsQuery.data],
  )

  const totals = useMemo(
    () => ({
      services: carriers.reduce((sum, item) => sum + item.services.length, 0),
      mappings: carriers.reduce((sum, item) => sum + item.platformMappings.length, 0),
    }),
    [carriers],
  )

  const toggleMapping = async (mapping: LogisticsPlatformCarrierMapping, active: boolean) => {
    try {
      await updateMapping.mutateAsync({
        mappingId: mapping.id,
        data: { versionId: mapping.versionId, status: active ? 'active' : 'inactive' },
      })
      void message.success(active ? '映射已启用' : '映射已停用')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '更新映射失败')
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Typography.Title level={3} style={{ marginBottom: 4 }}>
          承运商主数据
        </Typography.Title>
        <Typography.Text type="secondary">
          统一维护承运商、物流服务及平台承运商编码；当前发货适配器保持 Manual。
        </Typography.Text>
      </div>
      <LogisticsSectionNav />
      <Space wrap>
        <Card size="small">承运商：{carriers.length}</Card>
        <Card size="small">物流服务：{totals.services}</Card>
        <Card size="small">平台映射：{totals.mappings}</Card>
      </Space>
      <Card
        title="承运商列表"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCarrierModal(true)}>
            新增承运商
          </Button>
        }
      >
        <Table<LogisticsCarrier>
          rowKey="id"
          loading={query.isLoading}
          dataSource={carriers}
          pagination={false}
          columns={[
            { title: '编码', dataIndex: 'code' },
            { title: '承运商', dataIndex: 'name' },
            { title: 'Adapter', dataIndex: 'adapterKey', render: (value: string) => <Tag>{value}</Tag> },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value: string) => <Tag color={value === 'active' ? 'green' : 'default'}>{value}</Tag>,
            },
            { title: '服务数', render: (_, item) => item.services.length },
            { title: '映射数', render: (_, item) => item.platformMappings.length },
            {
              title: '操作',
              render: (_, item) => (
                <Space>
                  <Button type="link" onClick={() => setServiceCarrier(item)}>
                    新增服务
                  </Button>
                  <Button type="link" onClick={() => setMappingCarrier(item)}>
                    新增映射
                  </Button>
                </Space>
              ),
            },
          ]}
          expandable={{
            expandedRowRender: (carrier) => (
              <CarrierDetails carrier={carrier} shopNames={shopNames} onToggle={toggleMapping} />
            ),
          }}
          locale={{ emptyText: <Empty description="暂无承运商，请先创建主数据" /> }}
        />
      </Card>
      <CarrierCreateModal open={carrierModal} onClose={() => setCarrierModal(false)} />
      <CarrierServiceCreateModal
        carrier={serviceCarrier}
        open={Boolean(serviceCarrier)}
        onClose={() => setServiceCarrier(null)}
      />
      <PlatformMappingCreateModal
        carrier={mappingCarrier}
        open={Boolean(mappingCarrier)}
        onClose={() => setMappingCarrier(null)}
      />
    </Space>
  )
}

function CarrierDetails({
  carrier,
  shopNames,
  onToggle,
}: {
  carrier: LogisticsCarrier
  shopNames: Map<string, string>
  onToggle: (mapping: LogisticsPlatformCarrierMapping, active: boolean) => Promise<void>
}) {
  const serviceNames = new Map(carrier.services.map((item) => [item.id, item.name]))
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Text strong>物流服务</Typography.Text>
      <Table<LogisticsCarrierService>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={carrier.services}
        columns={[
          { title: '编码', dataIndex: 'code' },
          { title: '名称', dataIndex: 'name' },
          { title: '等级', dataIndex: 'serviceLevel', render: (value: string | null) => value || '-' },
          {
            title: '适用国家/地区',
            dataIndex: 'supportedCountries',
            render: (value: string[]) => value.join(', ') || '-',
          },
        ]}
      />
      <Typography.Text strong>平台承运商映射</Typography.Text>
      <Table<LogisticsPlatformCarrierMapping>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={carrier.platformMappings}
        columns={[
          { title: '平台', dataIndex: 'platform' },
          {
            title: '店铺',
            dataIndex: 'storeId',
            render: (value: string) => shopNames.get(value) || value,
          },
          { title: '地区', dataIndex: 'region' },
          { title: '平台 ID', dataIndex: 'platformCarrierId' },
          {
            title: '平台编码',
            dataIndex: 'platformCarrierCode',
            render: (value: string | null) => value || '-',
          },
          {
            title: '配送选项 ID',
            dataIndex: 'deliveryOptionId',
            render: (value: string | null) => value || '全部',
          },
          {
            title: '平台名称',
            dataIndex: 'platformCarrierName',
            render: (value: string | null) => value || '-',
          },
          {
            title: '限定服务',
            dataIndex: 'serviceId',
            render: (value: string | null) => (value ? serviceNames.get(value) || value : '全部服务'),
          },
          {
            title: '启用',
            render: (_, mapping) => (
              <Switch
                checked={mapping.status === 'active'}
                loading={false}
                onChange={(active) => void onToggle(mapping, active)}
              />
            ),
          },
        ]}
      />
    </Space>
  )
}

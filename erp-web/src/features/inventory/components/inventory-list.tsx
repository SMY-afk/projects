import type { ColumnsType } from 'antd/es/table'
import { ErpListPage } from '@/shared/components/erp-list/erp-list-page'
import type { InventoryItem } from '../types/inventory.types'
export function InventoryList({ data }: { data: InventoryItem[] }) {
  const columns: ColumnsType<InventoryItem> = [
    { title: '商品', dataIndex: 'name' },
    { title: 'SKU', dataIndex: 'code' },
    { title: '仓库', dataIndex: 'warehouse' },
    { title: '可用库存', dataIndex: 'available', align: 'right' },
    { title: '在途', dataIndex: 'inTransit', align: 'right' },
    { title: '状态', dataIndex: 'status' },
  ]
  return (
    <ErpListPage
      actionPermissions={{ batchDelete: 'warehouse:delete', viewDetail: 'warehouse:view' }}
      columns={columns}
      data={data}
      description="管理仓库库存、在途数量和预警状态"
      detailFields={[
        { label: '商品', key: 'name' },
        { label: 'SKU', key: 'code' },
        { label: '仓库', key: 'warehouse' },
        { label: '可用库存', key: 'available' },
        { label: '在途数量', key: 'inTransit' },
        { label: '状态', key: 'status' },
      ]}
      filterField="status"
      filterOptions={[
        { label: '正常', value: '正常' },
        { label: '预警', value: '预警' },
      ]}
      searchFields={['name', 'code', 'warehouse']}
      title="库存列表"
    />
  )
}

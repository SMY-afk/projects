import type { ColumnsType } from 'antd/es/table'
import { ErpListPage } from '@/shared/components/erp-list/erp-list-page'
import type { SettingItem } from '../types/setting.types'
export function SettingList({ data }: { data: SettingItem[] }) {
  const columns: ColumnsType<SettingItem> = [
    { title: '配置名称', dataIndex: 'name' },
    { title: '配置键', dataIndex: 'code' },
    { title: '分类', dataIndex: 'category' },
    { title: '值', dataIndex: 'value' },
    { title: '状态', dataIndex: 'status' },
    { title: '更新时间', dataIndex: 'updatedAt' },
  ]
  return (
    <ErpListPage
      actionPermissions={{ batchDelete: 'settings:delete', viewDetail: 'settings:view' }}
      columns={columns}
      data={data}
      description="管理订单、库存与通知等系统级配置"
      detailFields={[
        { label: '配置名称', key: 'name' },
        { label: '配置键', key: 'code' },
        { label: '分类', key: 'category' },
        { label: '值', key: 'value' },
        { label: '状态', key: 'status' },
        { label: '维护人', key: 'owner' },
      ]}
      filterField="status"
      filterOptions={[
        { label: '启用', value: '启用' },
        { label: '停用', value: '停用' },
      ]}
      searchFields={['name', 'code', 'category']}
      title="系统设置"
    />
  )
}

import { DeleteOutlined, DownOutlined, EyeOutlined, SearchOutlined, UpOutlined } from '@ant-design/icons'
import { Button, Drawer, Input, Select, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ReactNode } from 'react'
import { useMemo, useState } from 'react'
import { useAuth } from '@/auth/use-auth'
import './erp-list-page.css'

type ListRecord = { id: string }

export interface ErpListPageProps<T extends ListRecord> {
  title: string
  headerExtra?: ReactNode
  headerFilter?: ReactNode
  description: string
  data: T[]
  columns: ColumnsType<T>
  searchFields: Array<keyof T>
  filterOptions?: Array<{ label: string; value: string }>
  filterField?: keyof T
  detailFields: Array<{ label: string; key: keyof T }>
  actionPermissions?: { batchDelete?: string; viewDetail?: string }
  onOpenDetail?: (id: string) => void
  pagination?: { current: number; pageSize: number; total: number }
  onPageChange?: (page: number, pageSize: number) => void
  onSearchChange?: (value: string) => void
  onFilterChange?: (value?: string) => void
  onReset?: () => void
  serverSide?: boolean
  expandable?: (record: T) => ReactNode
  enableRowSelection?: boolean
}

export function ErpListPage<T extends ListRecord>({
  title,
  headerExtra,
  headerFilter,
  description,
  data,
  columns,
  searchFields,
  filterOptions = [],
  filterField,
  detailFields,
  actionPermissions,
  onOpenDetail,
  pagination,
  onPageChange,
  onSearchChange,
  onFilterChange,
  onReset,
  serverSide = false,
  expandable,
  enableRowSelection = true,
}: ErpListPageProps<T>) {
  const { hasPermissions } = useAuth()
  const [keyword, setKeyword] = useState('')
  const [filterValue, setFilterValue] = useState<string>()
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([])
  const [expandedRowKeys, setExpandedRowKeys] = useState<React.Key[]>([])
  const [detailRecord, setDetailRecord] = useState<T | null>(null)
  const canBatchDelete = !actionPermissions?.batchDelete || hasPermissions([actionPermissions.batchDelete])
  const canViewDetail = !actionPermissions?.viewDetail || hasPermissions([actionPermissions.viewDetail])
  const filteredData = useMemo(
    () =>
      data.filter((record) => {
        const matchesKeyword =
          !keyword ||
          searchFields.some((field) =>
            String(record[field] ?? '')
              .toLowerCase()
              .includes(keyword.toLowerCase()),
          )
        const matchesFilter = !filterValue || !filterField || String(record[filterField]) === filterValue
        return matchesKeyword && matchesFilter
      }),
    [data, filterField, filterValue, keyword, searchFields],
  )
  const displayData = serverSide ? data : filteredData
  const handleOpenDetail = (record: T) => {
    setDetailRecord(record)
    onOpenDetail?.(record.id)
  }
  const operationColumn: ColumnsType<T>[number] = {
    title: '操作',
    key: 'operation',
    fixed: 'right',
    width: expandable ? 170 : 88,
    render: (_, record) =>
      canViewDetail && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {expandable && (
            <Button
              aria-expanded={expandedRowKeys.includes(record.id)}
              icon={expandedRowKeys.includes(record.id) ? <UpOutlined /> : <DownOutlined />}
              onClick={() =>
                setExpandedRowKeys((keys) =>
                  keys.includes(record.id) ? keys.filter((key) => key !== record.id) : [...keys, record.id],
                )
              }
              size="small"
              type="link"
            >
              {expandedRowKeys.includes(record.id) ? '收起 SKU' : '展开 SKU'}
            </Button>
          )}
          <Button icon={<EyeOutlined />} onClick={() => handleOpenDetail(record)} size="small" type="link">
            详情
          </Button>
        </div>
      ),
  }

  return (
    <section className="erp-list-page">
      <header className="erp-list-header">
        <div>
          <div className="erp-list-title-row">
            <Typography.Title level={4}>{title}</Typography.Title>
            {headerExtra}
            {headerFilter}
          </div>
          <Typography.Text type="secondary">{description}</Typography.Text>
        </div>
      </header>
      <div className="erp-list-filters">
        <Input
          allowClear
          onChange={(event) => {
            setKeyword(event.target.value)
            onSearchChange?.(event.target.value)
          }}
          placeholder="搜索名称、编号或关键字"
          prefix={<SearchOutlined />}
          value={keyword}
        />
        {filterField && (
          <Select
            allowClear
            onChange={(value) => {
              setFilterValue(value)
              onFilterChange?.(value)
            }}
            options={filterOptions}
            placeholder="全部状态"
            style={{ minWidth: 144 }}
            value={filterValue}
          />
        )}
        <Button
          onClick={() => {
            setKeyword('')
            setFilterValue(undefined)
            onSearchChange?.('')
            onFilterChange?.(undefined)
            onReset?.()
          }}
        >
          重置
        </Button>
      </div>
      {enableRowSelection && (
        <div className="erp-list-batch-bar">
          <span>已选择 {selectedKeys.length} 项</span>
          {canBatchDelete && (
            <Button danger disabled={!selectedKeys.length} icon={<DeleteOutlined />}>
              批量删除
            </Button>
          )}
        </div>
      )}
      <Table<T>
        columns={[...columns, operationColumn]}
        dataSource={displayData}
        pagination={
          pagination
            ? { ...pagination, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }
            : { defaultPageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }
        }
        rowKey="id"
        onChange={(paginationState) => {
          if (serverSide && paginationState.current && paginationState.pageSize)
            onPageChange?.(paginationState.current, paginationState.pageSize)
        }}
        rowSelection={enableRowSelection ? { selectedRowKeys: selectedKeys, onChange: setSelectedKeys } : undefined}
        expandable={
          expandable
            ? {
                expandedRowRender: expandable,
                expandedRowKeys,
                onExpandedRowsChange: (keys) => setExpandedRowKeys([...keys]),
                showExpandColumn: false,
              }
            : undefined
        }
        scroll={{ x: 2100 }}
        size="middle"
      />
      <Drawer
        destroyOnHidden
        onClose={() => setDetailRecord(null)}
        open={Boolean(detailRecord)}
        size="large"
        title={`${title}详情`}
      >
        {detailRecord && (
          <dl className="erp-detail-list">
            {detailFields.map((field) => (
              <div key={String(field.key)}>
                <dt>{field.label}</dt>
                <dd>
                  {typeof detailRecord[field.key] === 'boolean' ? (
                    <Tag color={detailRecord[field.key] ? 'green' : 'default'}>
                      {detailRecord[field.key] ? '启用' : '停用'}
                    </Tag>
                  ) : (
                    String(detailRecord[field.key] ?? '-')
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </Drawer>
    </section>
  )
}

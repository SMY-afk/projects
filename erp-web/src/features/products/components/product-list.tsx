import type { ColumnsType } from 'antd/es/table'
import { Select, Table, Typography } from 'antd'
import { ErpListPage } from '@/shared/components/erp-list/erp-list-page'
import { modulePermissionCodes } from '@/auth/permission-codes'
import type { Product, ProductSku, ShopOption } from '../types/product.types'
import { ProductThumbnail } from './product-thumbnail'
import { formatCurrentPrice } from './product-price'
import './product-list.css'

const statusLabels: Record<string, string> = {
  ACTIVATE: '在售',
  DRAFT: '草稿',
  FREEZE: '冻结',
  DEACTIVATE: '已下架',
  SELLER_DEACTIVATE: '卖家下架',
  SELLER_DEACTIVATED: '卖家下架',
  PLATFORM_DEACTIVATED: '平台下架',
  PENDING: '审核中',
  FAILED: '审核失败',
  DELETED: '已删除',
  在售: '在售',
  草稿: '草稿',
  冻结: '冻结',
}

function formatProductStatus(status: string) {
  return statusLabels[status] ?? status
}

function SkuTable({ skus }: { skus: ProductSku[] }) {
  if (!skus.length) return <Typography.Text type="secondary">暂无 SKU 数据</Typography.Text>
  return (
    <div className="product-sku-panel">
      <Typography.Text type="secondary">{skus.length} 个 SKU</Typography.Text>
      <Table<ProductSku>
        columns={[
          { title: '商家 SKU 编码', dataIndex: 'sellerSku' },
          { title: '平台 SKU ID', dataIndex: 'platformSkuId' },
          { title: '库存', dataIndex: 'stock' },
          { title: '价格', render: (_, sku) => `${sku.currency} ${(sku.priceMinor / 100).toFixed(2)}` },
        ]}
        dataSource={skus}
        pagination={false}
        rowKey="id"
        size="small"
      />
    </div>
  )
}

export function ProductList({
  data,
  pagination,
  onPageChange,
  onSearchChange,
  onFilterChange,
  onOpenDetail,
  shopOptions,
  selectedShopId,
  onShopChange,
}: {
  data: Product[]
  pagination: { current: number; pageSize: number; total: number }
  onPageChange: (page: number, pageSize: number) => void
  onSearchChange: (value: string) => void
  onFilterChange: (value?: string) => void
  onOpenDetail: (id: string, shopId: string) => void
  shopOptions: ShopOption[]
  selectedShopId?: string
  onShopChange: (value?: string) => void
}) {
  const selectedShopName = selectedShopId
    ? shopOptions.find((shop) => shop.id === selectedShopId)?.shopName
    : data[0]?.shopName
  const columns: ColumnsType<Product> = [
    {
      title: '图片',
      dataIndex: 'imageUrl',
      width: 76,
      render: (_, record) => <ProductThumbnail imageUrl={record.imageUrl} alt={record.name} />,
    },
    {
      title: '商品名称',
      dataIndex: 'name',
      width: 220,
      render: (name: string) => (
        <Typography.Text className="product-name-text" title={name} ellipsis>
          {name}
        </Typography.Text>
      ),
    },
    { title: '商品 ID', dataIndex: 'id', width: 190, render: (id: string) => `product_id: ${id}` },
    {
      title: '当前售价',
      dataIndex: 'currentPrice',
      width: 180,
      render: (_, product) => {
        const price = formatCurrentPrice(product)
        return price ? (
          <Typography.Text strong style={{ color: '#087f5b' }}>
            {price}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">未设置售价</Typography.Text>
        )
      },
    },
    { title: '库存', dataIndex: 'stock', align: 'right' },
    { title: '状态', dataIndex: 'status', render: (status: string) => formatProductStatus(status) },
    { title: '更新时间', dataIndex: 'updatedAt' },
  ]
  return (
    <ErpListPage
      actionPermissions={{ batchDelete: 'products:delete', viewDetail: modulePermissionCodes.productsView }}
      columns={columns}
      data={data}
      headerExtra={
        <div className="product-list-header-extra">
          {selectedShopName && (
            <Typography.Text className="product-list-shop-name" strong title={selectedShopName}>
              店铺：{selectedShopName}
            </Typography.Text>
          )}
          <Typography.Text type="secondary">当前页 {data.length} 条</Typography.Text>
        </div>
      }
      headerFilter={
        <Select
          allowClear
          loading={!shopOptions.length}
          onChange={onShopChange}
          options={shopOptions.map((shop) => ({ label: shop.shopName, value: shop.id }))}
          placeholder="全部店铺"
          style={{ minWidth: 180 }}
          value={selectedShopId}
        />
      }
      pagination={pagination}
      onPageChange={onPageChange}
      onSearchChange={onSearchChange}
      onFilterChange={onFilterChange}
      onOpenDetail={(id) => {
        const product = data.find((item) => item.id === id)
        onOpenDetail(id, product?.shopId ?? '')
      }}
      expandable={(product) => <SkuTable skus={product.skus} />}
      serverSide
      description="管理商品信息、SKU 和上架状态"
      detailFields={[
        { label: '商品名称', key: 'name' },
        { label: '商家 SKU', key: 'sellerSku' },
        { label: '当前售价', key: 'currentPrice' },
        { label: '分类', key: 'category' },
        { label: '库存', key: 'stock' },
        { label: '店铺', key: 'shopName' },
        { label: '状态', key: 'status' },
      ]}
      filterField="status"
      filterOptions={[
        { label: '在售', value: 'ACTIVATE' },
        { label: '草稿', value: 'DRAFT' },
        { label: '冻结', value: 'FREEZE' },
      ]}
      searchFields={['name', 'code']}
      title="商品列表"
    />
  )
}

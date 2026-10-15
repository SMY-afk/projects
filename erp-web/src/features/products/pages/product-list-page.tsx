import { useState } from 'react'
import { useNavigate } from 'react-router'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { HttpError } from '@/services/http-client'
import { ProductList } from '../components/product-list'
import { useProductListQuery, useShopOptionsQuery } from '../queries/product.queries'
import type { ProductListParams } from '../types/product.types'
export default function ProductListPage() {
  const navigate = useNavigate()
  const [params, setParams] = useState<ProductListParams>({ page: 1, pageSize: 10 })
  const query = useProductListQuery(params)
  const shopsQuery = useShopOptionsQuery()
  if (query.isLoading) return <PageLoading fullscreen />
  if (query.isError || !query.data) {
    const error = query.error
    const tiktokUnavailable =
      error instanceof HttpError &&
      (error.kind === 'network' || error.kind === 'timeout' || [429, 502, 503, 504].includes(error.status ?? 0))
    return (
      <PageError
        description={
          tiktokUnavailable
            ? 'TikTok Shop 暂时不可用，商品数据未更新。请稍后重试。'
            : error instanceof Error
              ? error.message
              : undefined
        }
        onRetry={() => void query.refetch()}
        title={tiktokUnavailable ? 'TikTok Shop 暂时不可用' : undefined}
      />
    )
  }
  return (
    <ProductList
      data={query.data.items}
      pagination={{ current: query.data.page, pageSize: query.data.pageSize, total: query.data.total }}
      shopOptions={shopsQuery.data ?? []}
      selectedShopId={params.shopId}
      onShopChange={(shopId) => setParams((current) => ({ ...current, page: 1, shopId }))}
      onFilterChange={(status) => setParams((current) => ({ ...current, page: 1, status }))}
      onPageChange={(page, pageSize) => setParams((current) => ({ ...current, page, pageSize }))}
      onSearchChange={(keyword) => setParams((current) => ({ ...current, page: 1, keyword }))}
      onOpenDetail={(id, shopId) => void navigate(`/products/${id}?shopId=${encodeURIComponent(shopId)}`)}
    />
  )
}

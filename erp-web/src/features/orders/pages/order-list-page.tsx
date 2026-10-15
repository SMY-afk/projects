import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { HttpError } from '@/services/http-client'
import { getOrderTypeFilters, getOrderTypePath } from '../components/order-filter-options'
import { OrderList } from '../components/order-list'
import { useOrderListQuery, useOrderShopOptionsQuery } from '../queries/order.queries'
import type { OrderListParams, OrderStatus } from '../types/order.types'

export default function OrderListPage() {
  const navigate = useNavigate()
  const [params, setParams] = useState<OrderListParams>({ page: 1, pageSize: 20 })
  const [searchKeyword, setSearchKeyword] = useState('')
  useEffect(() => {
    const timeout = window.setTimeout(() => {
      const keyword = searchKeyword.trim() || undefined
      setParams((current) => (current.keyword === keyword ? current : { ...current, page: 1, keyword }))
    }, 350)
    return () => window.clearTimeout(timeout)
  }, [searchKeyword])
  const query = useOrderListQuery(params)
  const shopsQuery = useOrderShopOptionsQuery()
  if (query.isLoading) return <PageLoading fullscreen />
  if (query.isError || !query.data) {
    const unavailable = query.error instanceof HttpError && [429, 502, 503, 504].includes(query.error.status ?? 0)
    return (
      <PageError
        description={
          unavailable
            ? 'TikTok Shop 订单暂时不可用，请稍后重试。'
            : query.error instanceof Error
              ? query.error.message
              : undefined
        }
        onRetry={() => void query.refetch()}
        title={unavailable ? '订单数据暂时不可用' : undefined}
      />
    )
  }
  return (
    <OrderList
      data={query.data.items}
      onOpenDetail={(orderId) => void navigate(`/orders/${orderId}`)}
      onPageChange={(page, pageSize) => setParams((current) => ({ ...current, page, pageSize }))}
      onSearchChange={setSearchKeyword}
      onShopChange={(shopId) => setParams((current) => ({ ...current, page: 1, shopId }))}
      onStatusChange={(status?: OrderStatus) => setParams((current) => ({ ...current, page: 1, status }))}
      onAttributionChange={(field, value) =>
        setParams((current) => ({ ...current, page: 1, [field]: value || undefined }))
      }
      onOrderTypeChange={(path) => {
        const filters = getOrderTypeFilters(path)
        setParams((current) => ({
          ...current,
          page: 1,
          trafficSource: undefined,
          operatorSubject: undefined,
          entryPoint: undefined,
          specialOrderType: undefined,
          contentForm: undefined,
          ...filters,
        }))
      }}
      onContentFormChange={(contentForm) => setParams((current) => ({ ...current, page: 1, contentForm }))}
      onReset={() =>
        setParams((current) => ({
          page: 1,
          pageSize: current.pageSize,
          shopId: current.shopId,
        }))
      }
      pagination={{ current: query.data.page, pageSize: query.data.pageSize, total: query.data.total }}
      selectedShopId={params.shopId}
      selectedContentForm={params.contentForm}
      selectedOrderTypePath={getOrderTypePath(params)}
      shopOptions={shopsQuery.data ?? []}
    />
  )
}

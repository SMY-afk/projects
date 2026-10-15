import { useQuery } from '@tanstack/react-query'
import { productApi } from '../api/product.api'
import type { ProductListParams } from '../types/product.types'
export const productQueryKeys = {
  all: ['products'] as const,
  list: (params: ProductListParams) => ['products', 'list', params] as const,
}
export const useProductListQuery = (params: ProductListParams) =>
  useQuery({ queryKey: productQueryKeys.list(params), queryFn: () => productApi.getList(params) })
export const useShopOptionsQuery = () =>
  useQuery({ queryKey: ['shops', 'options'], queryFn: () => productApi.listShops() })
export const useProductDetailQuery = (productId: string, shopId?: string) =>
  useQuery({
    queryKey: ['products', 'detail', shopId, productId],
    queryFn: () => productApi.getDetail(productId, shopId),
    enabled: Boolean(productId && shopId),
  })

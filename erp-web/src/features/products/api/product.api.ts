import type { Product, ProductDetail, ProductListParams, ProductListResult, ShopOption } from '../types/product.types'
import { request } from '@/services/http-client'
import { isFeatureMockEnabled } from '@/services/api-mode'
const products: Product[] = [
  {
    id: '9957512936780642274',
    shopId: 'mock-shop',
    name: '蓝色童车',
    code: 'A-AHKLD-BLUE',
    status: '在售',
    updatedAt: '2026-08-10 10:20',
    owner: '商品组',
    shopName: 'Akeleo Fun Toys',
    skus: [
      {
        id: 'sku-1001-1',
        platformSkuId: 'A010050009',
        sellerSku: 'Excavator +Bulldozer+Dump Truck +Loader',
        stock: 248,
        priceMinor: 2000,
        currency: '$',
      },
      {
        id: 'sku-1001-2',
        platformSkuId: 'A010050004',
        sellerSku: 'Excavator +Bulldozer+Dump Truck',
        stock: 0,
        priceMinor: 1800,
        currency: '$',
      },
      {
        id: 'sku-1001-3',
        platformSkuId: 'A-EXCAVATOR',
        sellerSku: 'Excavator',
        stock: 0,
        priceMinor: 7000,
        currency: '$',
      },
      {
        id: 'sku-1001-4',
        platformSkuId: 'A010050003',
        sellerSku: 'Bulldozer',
        stock: 154,
        priceMinor: 6800,
        currency: '$',
      },
    ],
    category: '童车',
    stock: 680,
  },
  {
    id: 'P-1002',
    shopId: 'mock-shop',
    name: '红色童车',
    code: 'A-AHKLD-RED',
    status: '在售',
    updatedAt: '2026-08-09 16:30',
    owner: '商品组',
    shopName: 'Akeleo Fun Toys',
    skus: [],
    category: '童车',
    stock: 420,
  },
  {
    id: 'P-1003',
    shopId: 'mock-shop',
    name: '旅行配件套装',
    code: 'TRAVEL-SET-01',
    status: '草稿',
    updatedAt: '2026-08-08 09:10',
    owner: '运营组',
    shopName: 'Akeleo Fun Toys',
    skus: [],
    category: '配件',
    stock: 36,
  },
]
const mockProductApi = {
  getList: (params: ProductListParams): Promise<ProductListResult> => {
    const keyword = params.keyword?.trim().toLowerCase()
    const filtered = products.filter((product) => {
      const matchesKeyword =
        !keyword || [product.name, product.code].some((value) => value.toLowerCase().includes(keyword))
      return (
        matchesKeyword &&
        (!params.status || product.status === params.status) &&
        (!params.shopId || params.shopId === 'mock-shop')
      )
    })
    const start = (params.page - 1) * params.pageSize
    return Promise.resolve({
      items: filtered.slice(start, start + params.pageSize),
      total: filtered.length,
      page: params.page,
      pageSize: params.pageSize,
    })
  },
  getDetail: (productId: string, shopId?: string): Promise<ProductDetail> =>
    Promise.resolve({
      ...(products.find((product) => product.id === productId && (!shopId || product.shopId === shopId)) ??
        products[0]),
      description: null,
      imageUrls: [],
      categoryChain: [],
      packageWeight: null,
      packageDimensions: {},
      brand: null,
    }),
  listShops: (): Promise<ShopOption[]> =>
    Promise.resolve([
      { id: 'mock-shop', shopName: 'Akeleo Fun Toys', platform: 'tiktok', platformShopId: 'mock-tiktok-shop' },
    ]),
}
const httpProductApi = {
  getList: (params: ProductListParams) => request<ProductListResult>({ method: 'get', url: '/products', params }),
  getDetail: (productId: string, shopId?: string) =>
    request<ProductDetail>({ method: 'get', url: `/products/${productId}`, params: { shopId } }),
  listShops: () => request<ShopOption[]>({ method: 'get', url: '/shops' }),
}
export const productApi = isFeatureMockEnabled('products') ? mockProductApi : httpProductApi

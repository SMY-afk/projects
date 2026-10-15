export interface Product {
  id: string
  shopId: string
  name: string
  code: string
  status: string
  updatedAt: string
  owner: string
  shopName: string
  category: string
  stock: number
  imageUrl?: string | null
  sellerSku?: string | null
  currentPrice?: string | null
  skus: ProductSku[]
}

export interface ProductSku {
  id: string
  platformSkuId: string
  sellerSku: string
  stock: number
  priceMinor: number
  currency: string
}

export interface ProductListParams {
  page: number
  pageSize: number
  keyword?: string
  status?: string
  shopId?: string
}

export interface ShopOption {
  id: string
  shopName: string
  platform: string
  platformShopId: string
}

export interface ProductListResult {
  items: Product[]
  total: number
  page: number
  pageSize: number
}

export interface ProductDetail extends Product {
  description: string | null
  imageUrls: string[]
  categoryChain: string[]
  packageWeight: string | null
  packageDimensions: Record<string, string>
  brand: string | null
}

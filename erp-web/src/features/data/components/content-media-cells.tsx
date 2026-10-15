import { Tooltip } from 'antd'
import { ProductThumbnail } from '@/features/products/components/product-thumbnail'

const displayText = (value: unknown) => (typeof value === 'string' && value.trim() ? value : '--')

export const renderVideoTitle = (value: unknown) => {
  const title = displayText(value)
  return title === '--' ? (
    title
  ) : (
    <Tooltip title={title} placement="topLeft">
      <span className="data-video-title">{title}</span>
    </Tooltip>
  )
}

type PromotedProduct = {
  id: string
  name: string
  imageUrl?: string
}

const isPromotedProduct = (value: unknown): value is PromotedProduct => {
  if (!value || typeof value !== 'object') return false
  const product = value as Record<string, unknown>
  return typeof product.id === 'string' && typeof product.name === 'string'
}

export const renderPromotedProducts = (value: unknown) => {
  if (!Array.isArray(value) || !value.length) return '--'
  const products = value.filter(isPromotedProduct)
  return products.length ? (
    <div className="data-promoted-products">
      {products.map((product) => (
        <Tooltip key={product.id} title={product.name || product.id}>
          <span className="data-promoted-product-image">
            <ProductThumbnail imageUrl={product.imageUrl} size={44} alt={product.name || '推广商品'} />
          </span>
        </Tooltip>
      ))}
    </div>
  ) : (
    '--'
  )
}

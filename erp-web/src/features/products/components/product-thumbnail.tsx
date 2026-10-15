import { Image } from 'antd'
import './product-thumbnail.css'

export function ProductThumbnail({
  imageUrl,
  size = 52,
  alt = '商品图片',
}: {
  imageUrl?: string | null
  size?: number
  alt?: string
}) {
  if (!imageUrl)
    return (
      <span aria-label={`${alt}暂无图片`} className="product-thumbnail-empty" style={{ height: size, width: size }}>
        暂无图片
      </span>
    )

  return <Image alt={alt} src={imageUrl} width={size} height={size} style={{ objectFit: 'cover' }} preview />
}

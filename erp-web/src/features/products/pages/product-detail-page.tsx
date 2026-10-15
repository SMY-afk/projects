import { ArrowLeftOutlined } from '@ant-design/icons'
import { Button, Descriptions, Image, Result, Spin, Typography } from 'antd'
import { useLocation, useNavigate, useParams } from 'react-router'
import { useProductDetailQuery } from '../queries/product.queries'

export default function ProductDetailPage() {
  const { productId = '' } = useParams()
  const navigate = useNavigate()
  const shopId = new URLSearchParams(useLocation().search).get('shopId') ?? undefined
  const query = useProductDetailQuery(productId, shopId)
  if (!shopId) {
    return (
      <Result
        status="warning"
        title="缺少店铺信息"
        subTitle="商品详情需要明确的店铺范围，请从商品列表重新打开。"
        extra={<Button onClick={() => void navigate('/products')}>返回商品列表</Button>}
      />
    )
  }
  if (query.isLoading) return <Spin />
  if (query.isError || !query.data) return <Result status="error" title="商品详情加载失败" />
  const product = query.data
  return (
    <section style={{ padding: 24 }}>
      <Button icon={<ArrowLeftOutlined />} onClick={() => void navigate('/products')} style={{ marginBottom: 16 }}>
        BACK
      </Button>
      <Typography.Title level={4}>{product.name}</Typography.Title>
      <Image.PreviewGroup>
        {product.imageUrls.map((url) => (
          <Image key={url} src={url} width={120} style={{ marginRight: 8 }} />
        ))}
      </Image.PreviewGroup>
      <Descriptions
        bordered
        column={1}
        style={{ marginTop: 16 }}
        items={[
          { label: '品牌', children: product.brand ?? '-' },
          { label: '商品描述', children: <div dangerouslySetInnerHTML={{ __html: product.description ?? '-' }} /> },
          { label: 'TikTok 类目', children: product.categoryChain.join(' / ') || '-' },
          { label: '包装重量', children: product.packageWeight ?? '-' },
          {
            label: '包装尺寸',
            children:
              Object.entries(product.packageDimensions)
                .map(([key, value]) => `${key}: ${value}`)
                .join(' / ') || '-',
          },
        ]}
      />
    </section>
  )
}

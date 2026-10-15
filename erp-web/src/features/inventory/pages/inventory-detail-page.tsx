import { useParams } from 'react-router'
import { Result } from 'antd'
export default function InventoryDetailPage() {
  const { inventoryId } = useParams()
  return <Result status="info" title="库存详情" subTitle={`库存记录 ${inventoryId} 的完整详情将接入详情 API。`} />
}

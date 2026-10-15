import { useParams } from 'react-router'
import { Result } from 'antd'
export default function SettingDetailPage() {
  const { settingId } = useParams()
  return <Result status="info" title="系统设置详情" subTitle={`配置 ${settingId} 的完整详情将接入详情 API。`} />
}

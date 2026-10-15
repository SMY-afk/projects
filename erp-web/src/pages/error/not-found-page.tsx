import { Button, Result } from 'antd'
import { useNavigate } from 'react-router'

export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <Result
      extra={
        <Button onClick={() => void navigate('/dashboard')} type="primary">
          返回仪表盘
        </Button>
      }
      status="404"
      subTitle="请确认访问地址是否正确。"
      title="页面不存在"
    />
  )
}

import { Button, Result } from 'antd'
import { useNavigate } from 'react-router'

export default function ForbiddenPage() {
  const navigate = useNavigate()

  return (
    <Result
      extra={
        <Button onClick={() => void navigate('/dashboard')} type="primary">
          返回仪表盘
        </Button>
      }
      status="403"
      subTitle="当前账号没有访问该页面的权限，请联系管理员开通。"
      title="无访问权限"
    />
  )
}

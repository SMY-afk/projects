import { Button, Result } from 'antd'

interface PageErrorProps {
  description?: string
  onRetry?: () => void
  title?: string
}

export default function PageError({
  description = '请检查网络连接或稍后重试。',
  onRetry,
  title = '加载失败',
}: PageErrorProps) {
  return (
    <Result
      className="page-error"
      extra={
        onRetry && (
          <Button onClick={onRetry} type="primary">
            重新加载
          </Button>
        )
      }
      status="error"
      subTitle={description}
      title={title}
    />
  )
}

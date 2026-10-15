import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { useAuth } from '@/auth/use-auth'
import './login-page.css'

interface LoginFormValues {
  username: string
  password: string
}

export default function LoginPage() {
  const [form] = Form.useForm<LoginFormValues>()
  const { isAuthenticated, login } = useAuth()
  const [loginError, setLoginError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const locationState = location.state as { from?: { pathname?: string }; sessionExpired?: boolean } | null
  const from = locationState?.from?.pathname || '/dashboard'

  if (isAuthenticated) return <Navigate replace to="/dashboard" />

  const handleSubmit = async (values: LoginFormValues) => {
    setLoginError(null)
    setIsSubmitting(true)
    try {
      await login({
        username: values.username,
        password: values.password,
      })
      void navigate(from, { replace: true })
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : '登录失败，请重试')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="login-brand">
          <span>万</span>
          <strong>万矩环通科技有限公司</strong>
        </div>
        <Card className="login-card" variant="borderless">
          <Typography.Title level={2}>欢迎回来</Typography.Title>
          <Typography.Paragraph type="secondary">请登录以进入企业资源管理平台</Typography.Paragraph>
          {locationState?.sessionExpired && (
            <Alert className="login-session-alert" message="登录已失效，请重新登录。" showIcon type="warning" />
          )}
          {loginError && <Alert className="login-session-alert" message={loginError} showIcon type="error" />}
          <Form
            form={form}
            layout="vertical"
            onFinish={(values) => void handleSubmit(values)}
            requiredMark={false}
            size="large"
          >
            <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input autoComplete="username" prefix={<UserOutlined />} placeholder="请输入用户名" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password autoComplete="current-password" prefix={<LockOutlined />} placeholder="请输入密码" />
            </Form.Item>
            <Button block htmlType="submit" type="primary" loading={isSubmitting}>
              登录
            </Button>
          </Form>
        </Card>
      </section>
    </main>
  )
}

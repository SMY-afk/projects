import type { ReactNode } from 'react'
import { App as AntdApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClientProvider } from '@tanstack/react-query'

import { queryClient } from './query-client'
import { appTheme } from './theme'
import { AuthProvider } from '@/auth/auth-context.tsx'

interface AppProvidersProps {
  children: ReactNode
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <ConfigProvider locale={zhCN} theme={appTheme}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <AntdApp>{children}</AntdApp>
        </AuthProvider>
      </QueryClientProvider>
    </ConfigProvider>
  )
}

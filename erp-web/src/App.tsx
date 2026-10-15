import { Suspense } from 'react'
import { Outlet } from 'react-router'

import { AppProviders } from '@/app/app-providers'
import { AuthStatusRedirect } from '@/auth/auth-status-redirect'
import PageLoading from '@/shared/components/page-state/page-loading'

export default function App() {
  return (
    <AppProviders>
      <AuthStatusRedirect />
      <Suspense fallback={<PageLoading fullscreen />}>
        <Outlet />
      </Suspense>
    </AppProviders>
  )
}

import { Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import App from '@/App'
import BasicLayout from '@/layouts/basic-layout/basic-layout'
import NotFoundPage from '@/pages/error/not-found-page'
import LoginPage from '@/pages/login/login-page'
import { appRouteMetadata } from '@/router/route-metadata'
import { RequireAuth, RequirePermission } from '@/router/route-guards'
import PageLoading from '@/shared/components/page-state/page-loading'

export default function AppRouter() {
  return (
    <Routes>
      <Route element={<App />}>
        <Route element={<LoginPage />} path="/login" />
        <Route element={<RequireAuth />}>
          <Route element={<BasicLayout />}>
            <Route index element={<Navigate replace to="/dashboard" />} />
            {appRouteMetadata.map((route) => (
              <Route element={<RequirePermission permissions={route.permissions} />} key={route.key}>
                <Route element={<Suspense fallback={<PageLoading />}>{route.element}</Suspense>} path={route.path} />
              </Route>
            ))}
            <Route element={<NotFoundPage />} path="*" />
          </Route>
        </Route>
      </Route>
    </Routes>
  )
}

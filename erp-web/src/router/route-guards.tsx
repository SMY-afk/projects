import { Navigate, Outlet, useLocation } from 'react-router'
import { useAuth } from '@/auth/use-auth'
import PageLoading from '@/shared/components/page-state/page-loading'

export function RequireAuth() {
  const { isAuthenticated, isInitializing } = useAuth()
  const location = useLocation()
  if (isInitializing) return <PageLoading fullscreen />
  return isAuthenticated ? <Outlet /> : <Navigate replace state={{ from: location }} to="/login" />
}

export function RequirePermission({ permissions }: { permissions?: string[] }) {
  const { hasPermissions } = useAuth()
  return hasPermissions(permissions) ? <Outlet /> : <Navigate replace to="/403" />
}

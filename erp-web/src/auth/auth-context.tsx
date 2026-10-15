import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { authApi, authQueryKeys, useCurrentUserQuery, useLoginMutation, useLogoutMutation } from '@/services/auth'
import { AUTH_UNAUTHORIZED_EVENT } from './auth-events'
import { AuthContext, type AuthContextValue } from './auth-context'
import { authSession } from './auth-session'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [hasSession, setHasSession] = useState(() => Boolean(authSession.getAccessToken()))
  const currentUserQuery = useCurrentUserQuery()
  const loginMutation = useLoginMutation()
  const logoutMutation = useLogoutMutation()
  const user = hasSession && !currentUserQuery.isError ? (currentUserQuery.data ?? null) : null
  const isInitializing = hasSession && currentUserQuery.isLoading

  const clearAuthentication = useCallback(() => {
    authSession.clear()
    setHasSession(false)
    queryClient.removeQueries({ queryKey: authQueryKeys.all })
  }, [queryClient])

  useEffect(() => {
    const handleUnauthorized = () => clearAuthentication()
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized)
    return () => window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, handleUnauthorized)
  }, [clearAuthentication])

  useEffect(() => {
    if (!currentUserQuery.isError) return
    authSession.clear()
    queryClient.removeQueries({ queryKey: authQueryKeys.all })
  }, [currentUserQuery.isError, queryClient])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isInitializing,
      hasPermissions: (permissions) =>
        !permissions?.length || permissions.every((permission) => user?.permissions.includes(permission)),
      login: async (payload) => {
        const { accessToken } = await loginMutation.mutateAsync(payload)
        authSession.setAccessToken(accessToken)
        setHasSession(true)
        try {
          await queryClient.fetchQuery({
            queryKey: authQueryKeys.currentUser(),
            queryFn: () => authApi.getCurrentUser(),
          })
        } catch (error) {
          clearAuthentication()
          throw error
        }
      },
      logout: () => {
        void logoutMutation.mutateAsync().finally(clearAuthentication)
      },
    }),
    [clearAuthentication, isInitializing, loginMutation, logoutMutation, queryClient, user],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

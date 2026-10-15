import { useMutation, useQuery } from '@tanstack/react-query'
import { authSession } from '@/auth/auth-session'
import { authApi } from './auth-client'
import type { LoginPayload } from './auth-api'

export const authQueryKeys = {
  all: ['auth'] as const,
  currentUser: () => [...authQueryKeys.all, 'current-user'] as const,
}

export const useCurrentUserQuery = () =>
  useQuery({
    queryKey: authQueryKeys.currentUser(),
    queryFn: () => authApi.getCurrentUser(),
    enabled: Boolean(authSession.getAccessToken()),
  })

export const useLoginMutation = () =>
  useMutation({
    mutationFn: (payload: LoginPayload) => authApi.login(payload),
  })

export const useLogoutMutation = () =>
  useMutation({
    mutationFn: () => authApi.logout(),
  })

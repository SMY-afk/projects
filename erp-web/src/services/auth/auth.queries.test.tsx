import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { authSession } from '@/auth/auth-session'
import type { AuthUser } from './auth-api'
import { authApi } from './auth-client'
import { authQueryKeys, useCurrentUserQuery } from './auth.queries'

describe('useCurrentUserQuery', () => {
  it('only fetches after an access token exists', async () => {
    window.sessionStorage.clear()
    const getCurrentUser = vi.spyOn(authApi, 'getCurrentUser')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result, rerender } = renderHook(() => useCurrentUserQuery(), { wrapper })
    expect(result.current.fetchStatus).toBe('idle')

    authSession.setAccessToken('mock-access-token-admin')
    rerender()
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(queryClient.getQueryData<AuthUser>(authQueryKeys.currentUser())?.username).toBe('admin')
    getCurrentUser.mockRestore()
  })
})

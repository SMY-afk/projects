import { act, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AUTH_UNAUTHORIZED_EVENT } from './auth-events'
import { AuthProvider } from './auth-context.tsx'
import { authSession } from './auth-session'
import { useAuth } from './use-auth'

const mocks = vi.hoisted(() => ({
  currentUser: {
    id: 'user-1',
    name: 'Admin',
    username: 'admin',
    roles: [],
    permissions: ['data:view'],
  },
}))

vi.mock('@/services/auth', () => ({
  authApi: { getCurrentUser: vi.fn() },
  authQueryKeys: { all: ['auth'], currentUser: () => ['auth', 'current-user'] },
  useCurrentUserQuery: () => ({ data: mocks.currentUser, isLoading: false, isError: false }),
  useLoginMutation: () => ({ mutateAsync: vi.fn() }),
  useLogoutMutation: () => ({ mutateAsync: vi.fn() }),
}))

function AuthState() {
  return <span>{useAuth().isAuthenticated ? 'authenticated' : 'signed-out'}</span>
}

describe('AuthProvider', () => {
  beforeEach(() => window.sessionStorage.clear())

  it('immediately drops the authenticated state after a 401 event', () => {
    authSession.setAccessToken('expired-token')
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthProvider>
          <AuthState />
        </AuthProvider>
      </QueryClientProvider>,
    )
    expect(screen.getByText('authenticated')).toBeInTheDocument()

    void act(() => window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT)))

    expect(screen.getByText('signed-out')).toBeInTheDocument()
    expect(authSession.getAccessToken()).toBeNull()
  })
})

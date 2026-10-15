import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AuthContextValue } from '@/auth/auth-context'
import { RequireAuth, RequirePermission } from './route-guards'

type GuardAuth = Pick<AuthContextValue, 'hasPermissions' | 'isAuthenticated' | 'isInitializing'>
const mocks = vi.hoisted(() => ({ useAuth: vi.fn<() => GuardAuth>() }))
vi.mock('@/auth/use-auth', () => ({ useAuth: mocks.useAuth }))

describe('route guards', () => {
  beforeEach(() => mocks.useAuth.mockReset())

  it('redirects unauthenticated users to login', () => {
    mocks.useAuth.mockReturnValue({ hasPermissions: () => false, isAuthenticated: false, isInitializing: false })
    render(
      <MemoryRouter initialEntries={['/orders']}>
        <Routes>
          <Route element={<RequireAuth />}>
            <Route element={<div>Orders</div>} path="/orders" />
          </Route>
          <Route element={<div>Login</div>} path="/login" />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText('Login')).toBeInTheDocument()
  })

  it('renders a permitted nested route', () => {
    mocks.useAuth.mockReturnValue({
      hasPermissions: (permissions?: string[]) => permissions?.includes('orders:view') ?? true,
      isAuthenticated: true,
      isInitializing: false,
    })
    render(
      <MemoryRouter initialEntries={['/orders']}>
        <Routes>
          <Route element={<RequirePermission permissions={['orders:view']} />}>
            <Route element={<div>Orders</div>} path="/orders" />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText('Orders')).toBeInTheDocument()
  })

  it('redirects a user without the route permission to 403', () => {
    mocks.useAuth.mockReturnValue({
      hasPermissions: () => false,
      isAuthenticated: true,
      isInitializing: false,
    })
    render(
      <MemoryRouter initialEntries={['/logistics/returns']}>
        <Routes>
          <Route element={<RequirePermission permissions={['returns:view']} />}>
            <Route element={<div>Returns</div>} path="/logistics/returns" />
          </Route>
          <Route element={<div>Forbidden</div>} path="/403" />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByText('Forbidden')).toBeInTheDocument()
    expect(screen.queryByText('Returns')).not.toBeInTheDocument()
  })
})

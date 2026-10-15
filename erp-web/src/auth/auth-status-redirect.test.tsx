import { act, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { AUTH_FORBIDDEN_EVENT, AUTH_UNAUTHORIZED_EVENT } from './auth-events'
import { AuthStatusRedirect } from './auth-status-redirect'

describe('AuthStatusRedirect', () => {
  it('navigates to the forbidden page after a server-side 403 event', async () => {
    render(
      <MemoryRouter initialEntries={['/orders']}>
        <Routes>
          <Route element={<AuthStatusRedirect />} path="/orders" />
          <Route element={<div>Forbidden</div>} path="/403" />
        </Routes>
      </MemoryRouter>,
    )

    await act(() => window.dispatchEvent(new Event(AUTH_FORBIDDEN_EVENT)))

    expect(screen.getByText('Forbidden')).toBeInTheDocument()
  })

  it('navigates to login after a server-side 401 event', async () => {
    render(
      <MemoryRouter initialEntries={['/data']}>
        <Routes>
          <Route element={<AuthStatusRedirect />} path="/data" />
          <Route element={<div>Login</div>} path="/login" />
        </Routes>
      </MemoryRouter>,
    )

    await act(() => window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT)))

    expect(screen.getByText('Login')).toBeInTheDocument()
  })
})

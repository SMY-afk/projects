import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { ErpListPage } from './erp-list-page'

vi.mock('@/auth/use-auth', () => ({
  useAuth: () => ({ hasPermissions: () => true }),
}))

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  window.matchMedia = vi.fn().mockImplementation(() => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
})

describe('ErpListPage reset', () => {
  it('notifies the feature page so controlled header filters are reset too', async () => {
    const onReset = vi.fn()
    const user = userEvent.setup()

    render(
      <ErpListPage
        columns={[]}
        data={[]}
        description="test"
        detailFields={[]}
        onReset={onReset}
        searchFields={[]}
        title="test"
      />,
    )

    await user.click(screen.getByRole('button', { name: /重\s*置/ }))

    expect(onReset).toHaveBeenCalledTimes(1)
  })
})

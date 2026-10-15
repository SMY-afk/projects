import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { BestsellerScopeStatus } from './bestseller-status-bars'

describe('BestsellerScopeStatus', () => {
  it('renders nothing when the required scopes are ready', () => {
    const { container } = render(
      <BestsellerScopeStatus
        onReauthorize={vi.fn()}
        reauthorizing={false}
        query={{
          data: {
            apiVersion: 'v1',
            source: 'local_connection',
            data: {
              shopId: 'shop-1',
              status: 'ready',
              requiredScopes: ['data.bestselling.public.read'],
              grantedScopes: ['data.bestselling.public.read'],
              missingScopes: [],
              canRead: true,
            },
            freshness: { isStale: false },
            errors: [],
          },
          isError: false,
          isLoading: false,
        }}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('offers target-shop reauthorization only when scopes are missing', async () => {
    const onReauthorize = vi.fn()
    const user = userEvent.setup()
    render(
      <BestsellerScopeStatus
        onReauthorize={onReauthorize}
        reauthorizing={false}
        query={{
          data: {
            apiVersion: 'v1',
            source: 'local_connection',
            data: {
              shopId: 'shop-1',
              status: 'reauthorization_required',
              requiredScopes: ['data.bestselling.public.read'],
              grantedScopes: [],
              missingScopes: ['data.bestselling.public.read'],
              canRead: false,
            },
            freshness: { isStale: false },
            errors: [],
          },
          isError: false,
          isLoading: false,
        }}
      />,
    )

    await user.click(screen.getByRole('button', { name: '重新授权' }))
    expect(onReauthorize).toHaveBeenCalledOnce()
  })
})

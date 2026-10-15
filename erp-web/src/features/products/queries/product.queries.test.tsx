import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { productApi } from '../api/product.api'
import { useProductDetailQuery } from './product.queries'

vi.mock('../api/product.api', () => ({
  productApi: {
    getDetail: vi.fn(),
  },
}))

describe('product queries', () => {
  beforeEach(() => vi.clearAllMocks())

  it('does not request product details without a shop id', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    renderHook(() => useProductDetailQuery('product-1'), { wrapper })
    await Promise.resolve()

    expect(productApi.getDetail).not.toHaveBeenCalled()
  })
})

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { AffiliateAvatar } from './affiliate-avatar'

describe('AffiliateAvatar', () => {
  beforeAll(() => {
    Object.defineProperty(window, 'matchMedia', { writable: true, value: vi.fn().mockImplementation(() => ({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })) })
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })
  it('replaces a failed avatar image with the creator initial', () => {
    render(<AffiliateAvatar alt="@yana_ok1" url="https://example.test/expired.jpg">Y</AffiliateAvatar>)
    fireEvent.error(screen.getByRole('img', { name: '@yana_ok1' }))
    expect(screen.queryByRole('img', { name: '@yana_ok1' })).not.toBeInTheDocument()
    expect(screen.getByText('Y')).toBeInTheDocument()
  })

  it('loads a refreshed URL after the previous image failed', () => {
    const { rerender } = render(<AffiliateAvatar alt="@yana_ok1" url="https://example.test/old.jpg">Y</AffiliateAvatar>)
    fireEvent.error(screen.getByRole('img', { name: '@yana_ok1' }))
    rerender(<AffiliateAvatar alt="@yana_ok1" url="https://example.test/current.jpg">Y</AffiliateAvatar>)
    expect(screen.getByRole('img', { name: '@yana_ok1' })).toHaveAttribute('src', 'https://example.test/current.jpg')
  })
})

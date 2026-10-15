import { fireEvent, render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { CreatorOpenId } from './creator-open-id'

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})

describe('CreatorOpenId', () => {
  it('shows a compact value, exposes the full value on hover, and provides copy control', async () => {
    const openId = 's9NNQwAAAACvfWKwPW83JHUJYNnIl2DbnAf__c7NFFBnEZVYnURnww'
    const { container } = render(<CreatorOpenId value={openId} />)

    const compactValue = screen.getByText('s9NNQwAA…URnww')
    expect(container.querySelector('.ant-typography-copy')).not.toBeNull()

    fireEvent.mouseEnter(compactValue)
    expect(await screen.findByRole('tooltip')).toHaveTextContent(openId)
  })
})

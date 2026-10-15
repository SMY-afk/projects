import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import DataUnavailablePage from './data-unavailable-page'

describe('DataUnavailablePage', () => {
  it('does not present pending metrics as real data', () => {
    render(<DataUnavailablePage />)

    expect(screen.getByText('真实数据暂不可用')).toBeInTheDocument()
    expect(screen.getByText(/不会显示 Mock、0 值或推测数据/)).toBeInTheDocument()
    expect(screen.getAllByText(/待确认：/)).toHaveLength(4)
  })
})

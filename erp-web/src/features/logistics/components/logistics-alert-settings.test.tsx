import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { LogisticsAlertSettings } from './logistics-alert-settings'

const update = vi.hoisted(() => vi.fn())
vi.mock('@/auth/use-auth', () => ({ useAuth: () => ({ hasPermissions: () => true }) }))
vi.mock('../api/logistics-status.api', () => ({ logisticsStatusApi: { updateAlertSettings: update } }))

it('saves a configurable advance time and keeps edits during background refresh', async () => {
  update.mockResolvedValue({ leadHours: 4 })
  const onSaved = vi.fn().mockResolvedValue(undefined)
  const view = render(<LogisticsAlertSettings hours={3} onSaved={onSaved} />)
  expect(Number((screen.getByRole('spinbutton', { name: '提前预警小时数' }) as HTMLInputElement).value)).toBe(3)
  fireEvent.change(screen.getByRole('spinbutton', { name: '提前预警小时数' }), { target: { value: '4' } })
  view.rerender(<LogisticsAlertSettings hours={3.5} onSaved={onSaved} />)
  expect(Number((screen.getByRole('spinbutton', { name: '提前预警小时数' }) as HTMLInputElement).value)).toBe(4)
  fireEvent.click(screen.getByRole('button', { name: '保存预警设置' }))
  await waitFor(() => expect(update).toHaveBeenCalledWith(4))
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
})

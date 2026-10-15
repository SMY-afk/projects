import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { LogisticsSectionNav } from './logistics-section-nav'

const mocks = vi.hoisted(() => ({ permissions: [] as string[] }))
vi.mock('antd', () => ({
  Menu: ({ items = [] }: { items?: { key: string; label: string }[] }) => (
    <nav>
      {items.map((item) => (
        <span key={item.key}>{item.label}</span>
      ))}
    </nav>
  ),
}))
vi.mock('@/auth/use-auth', () => ({
  useAuth: () => ({
    hasPermissions: (required?: string[]) => required?.every((code) => mocks.permissions.includes(code)) ?? true,
  }),
}))

describe('LogisticsSectionNav', () => {
  beforeEach(() => {
    mocks.permissions = []
  })

  it('shows logistics and returns as module-level secondary navigation', () => {
    mocks.permissions = [
      modulePermissionCodes.logisticsView,
      modulePermissionCodes.logisticsManage,
      modulePermissionCodes.returnsView,
    ]

    render(
      <MemoryRouter initialEntries={['/logistics']}>
        <LogisticsSectionNav />
      </MemoryRouter>,
    )

    expect(screen.getByText('任务中心')).toBeInTheDocument()
    expect(screen.getByText('异常中心')).toBeInTheDocument()
    expect(screen.getByText('物流状态')).toBeInTheDocument()
    expect(screen.getByText('退换货')).toBeInTheDocument()
    expect(screen.getByText('承运商管理')).toBeInTheDocument()
    expect(screen.getByText('物流状态').compareDocumentPosition(screen.getByText('退换货'))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
  })

  it('hides a secondary route when its permission is missing', () => {
    mocks.permissions = [modulePermissionCodes.logisticsView]

    render(
      <MemoryRouter initialEntries={['/logistics']}>
        <LogisticsSectionNav />
      </MemoryRouter>,
    )

    expect(screen.getByText('任务中心')).toBeInTheDocument()
    expect(screen.getByText('异常中心')).toBeInTheDocument()
    expect(screen.getByText('物流状态')).toBeInTheDocument()
    expect(screen.queryByText('退换货')).not.toBeInTheDocument()
    expect(screen.queryByText('承运商管理')).not.toBeInTheDocument()
  })
})

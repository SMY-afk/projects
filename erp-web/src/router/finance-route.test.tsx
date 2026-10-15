import { isValidElement } from 'react'
import { describe, expect, it } from 'vitest'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { getRouteByPath, getTopNavigation } from './route-metadata'

describe('Finance route', () => {
  it('replaces the placeholder with a permission-filtered Finance feature route', () => {
    const route = getRouteByPath('/finance')

    expect(route?.label).toBe('财务')
    expect(route?.permissions).toEqual([modulePermissionCodes.financeView])
    expect(getTopNavigation([modulePermissionCodes.financeView]).map((item) => item.path)).toContain('/finance')
    expect(getTopNavigation([]).map((item) => item.path)).not.toContain('/finance')
    expect(isValidElement(route?.element)).toBe(true)
    if (!isValidElement(route?.element)) throw new Error('Finance route element is missing')
    expect(String(route.element.type)).not.toContain('ModulePlaceholderPage')
  })

  it('registers Finance list and statement detail routes with the same permission', () => {
    const paths = [
      '/finance/orders',
      '/finance/statements',
      '/finance/statements/statement-1',
      '/finance/transactions',
      '/finance/payments',
      '/finance/reconciliation',
    ]

    for (const path of paths) {
      expect(getRouteByPath(path)?.permissions).toEqual([modulePermissionCodes.financeView])
      expect(isValidElement(getRouteByPath(path)?.element)).toBe(true)
    }
  })
})

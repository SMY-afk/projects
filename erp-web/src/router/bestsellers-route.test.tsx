import { describe, expect, it } from 'vitest'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { getRouteByPath, getTopNavigation } from './route-metadata'

describe('Bestsellers route', () => {
  it('adds a permission-filtered top navigation entry', () => {
    const route = getRouteByPath('/bestsellers')

    expect(route?.label).toBe('畅销榜')
    expect(route?.permissions).toEqual([modulePermissionCodes.bestsellersView])
    expect(getTopNavigation([modulePermissionCodes.bestsellersView]).map((item) => item.path)).toContain('/bestsellers')
    expect(getTopNavigation([]).map((item) => item.path)).not.toContain('/bestsellers')
  })
})

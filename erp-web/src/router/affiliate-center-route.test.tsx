import { describe, expect, it } from 'vitest'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { getRouteByPath, getTopNavigation } from './route-metadata'

describe('Affiliate Center route', () => {
  it('adds a permission-filtered top navigation entry after bestsellers', () => {
    const route = getRouteByPath('/affiliate-center')
    expect(route?.label).toBe('联盟中心')
    expect(route?.permissions).toEqual([modulePermissionCodes.affiliateCenterView])
    const navigationPaths = getTopNavigation([
      modulePermissionCodes.bestsellersView,
      modulePermissionCodes.affiliateCenterView,
    ]).map((item) => item.path)
    expect(navigationPaths).toEqual(['/bestsellers', '/affiliate-center'])
    expect(getTopNavigation([]).map((item) => item.path)).not.toContain('/affiliate-center')
  })

  it('redirects the parent route to creators and registers all resource routes', () => {
    expect(getRouteByPath('/affiliate-center')?.element).toMatchObject({
      props: { replace: true, to: '/affiliate-center/creators' },
    })
    expect(getRouteByPath('/affiliate-center/creators')?.label).toBe('达人')
    expect(getRouteByPath('/affiliate-center/videos')?.label).toBe('所有视频')
    expect(getRouteByPath('/affiliate-center/live-accounts')?.label).toBe('联盟账号直播数据')
  })
})

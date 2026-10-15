import { isValidElement } from 'react'
import { describe, expect, it } from 'vitest'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { getRouteByPath, getTopNavigation } from './route-metadata'

describe('Logistics routes', () => {
  it('replaces the logistics placeholder with a lazy permission-filtered feature route', () => {
    const route = getRouteByPath('/logistics')

    expect(route?.label).toBe('物流')
    expect(route?.permissions).toEqual([modulePermissionCodes.logisticsView])
    expect(getTopNavigation([modulePermissionCodes.logisticsView]).map((item) => item.path)).toContain('/logistics')
    expect(getTopNavigation([]).map((item) => item.path)).not.toContain('/logistics')
    expect(isValidElement(route?.element)).toBe(true)
    if (!isValidElement(route?.element)) throw new Error('Logistics route element is missing')
    expect(String(route.element.type)).not.toContain('ModulePlaceholderPage')
  })

  it('registers the returns page behind its own permission guard', () => {
    const route = getRouteByPath('/logistics/returns')

    expect(route?.label).toBe('退换货')
    expect(route?.permissions).toEqual([modulePermissionCodes.returnsView])
    expect(isValidElement(route?.element)).toBe(true)

    const detailRoute = getRouteByPath('/logistics/returns/return-1')
    expect(detailRoute?.label).toBe('退换货详情')
    expect(detailRoute?.permissions).toEqual([modulePermissionCodes.returnsView])
    expect(isValidElement(detailRoute?.element)).toBe(true)
  })

  it('registers the exception center under logistics view permission', () => {
    const route = getRouteByPath('/logistics/exceptions')

    expect(route?.label).toBe('物流异常中心')
    expect(route?.permissions).toEqual([modulePermissionCodes.logisticsView])
    expect(isValidElement(route?.element)).toBe(true)
  })

  it('registers carrier master data behind logistics manage permission', () => {
    const route = getRouteByPath('/logistics/carriers')

    expect(route?.permissions).toEqual([modulePermissionCodes.logisticsView, modulePermissionCodes.logisticsManage])
    expect(isValidElement(route?.element)).toBe(true)
  })

  it('keeps a single logistics entry in the top navigation', () => {
    const navigation = getTopNavigation([
      modulePermissionCodes.logisticsView,
      modulePermissionCodes.returnsView,
    ]).filter((item) => item.path.startsWith('/logistics'))

    expect(navigation.map((item) => item.path)).toEqual(['/logistics'])
  })

  it('registers task detail, review and package editor routes with scoped permissions', () => {
    expect(getRouteByPath('/logistics/tasks/task-1')?.permissions).toEqual([modulePermissionCodes.logisticsView])
    expect(getRouteByPath('/logistics/tasks/task-1/review')?.permissions).toEqual([
      modulePermissionCodes.logisticsView,
      modulePermissionCodes.logisticsOperate,
    ])
    expect(getRouteByPath('/logistics/tasks/task-1/packages/new')?.permissions).toEqual([
      modulePermissionCodes.logisticsView,
      modulePermissionCodes.logisticsOperate,
    ])
    expect(getRouteByPath('/logistics/tasks/task-1/shipping')?.permissions).toEqual([
      modulePermissionCodes.logisticsView,
      modulePermissionCodes.logisticsDispatch,
    ])
  })

  it('does not introduce warehouse, inventory, or transfer-order routes', () => {
    expect(getRouteByPath('/inventory')).toBeUndefined()
    expect(getRouteByPath('/transfer-orders')).toBeUndefined()
    expect(getRouteByPath('/warehouses')).toBeUndefined()
  })
})

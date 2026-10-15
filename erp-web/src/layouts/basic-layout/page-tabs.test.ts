import { beforeEach, describe, expect, it } from 'vitest'
import { getRouteByPath } from '@/router/route-metadata'
import { addPageTab, initialPageTabs, PINNED_TAB_PATH, removePageTab, restorePageTabs, tabForRoute } from './page-tabs'

const permissions = ['dashboard:view', 'orders:view', 'products:view', 'data:view']

describe('page tabs', () => {
  beforeEach(() => window.sessionStorage.clear())

  it('starts with the existing secondary navigation permitted to the user', () => {
    expect(initialPageTabs(permissions).map((tab) => tab.path)).toEqual(['/dashboard', '/orders', '/products'])
  })

  it('adds a clicked module once and keeps the home tab pinned', () => {
    const tabs = addPageTab(initialPageTabs(permissions), { path: '/data', label: 'Data' })

    expect(addPageTab(tabs, { path: '/data', label: 'Data' })).toEqual(tabs)
    expect(removePageTab(tabs, PINNED_TAB_PATH)).toEqual(tabs)
    expect(removePageTab(tabs, '/data').some((tab) => tab.path === '/data')).toBe(false)
  })

  it('preserves detail route query parameters in the tab target', () => {
    const route = getRouteByPath('/products/product-1')

    expect(tabForRoute('/products/product-1', route, '?shopId=shop-1')).toEqual({
      path: '/products/product-1?shopId=shop-1',
      label: route?.label,
    })
  })

  it('restores a detail tab with its query parameters intact', () => {
    const route = getRouteByPath('/products/product-1')
    window.sessionStorage.setItem(
      'tabs',
      JSON.stringify([{ path: '/products/product-1?shopId=shop-1', label: route?.label }]),
    )

    expect(restorePageTabs('tabs', permissions)).toContainEqual({
      path: '/products/product-1?shopId=shop-1',
      label: route?.label,
    })
  })
})

import type { AppRouteMetadata } from '@/router/route-metadata'
import { canAccessRoute, getRouteByPath, secondaryNavigation } from '@/router/route-metadata'

export interface PageTab {
  path: string
  label: string
}

export const PINNED_TAB_PATH = '/dashboard'
const MAX_OPEN_TABS = 12

export function initialPageTabs(permissions: string[]): PageTab[] {
  return secondaryNavigation.flatMap((item) => {
    const route = getRouteByPath(item.key)
    return route && canAccessRoute(route, permissions) ? [{ path: item.key, label: item.label }] : []
  })
}

export function tabForRoute(pathname: string, route: AppRouteMetadata | undefined, search = ''): PageTab | undefined {
  if (!route || route.key === '/403') return undefined
  return { path: `${pathname}${search}`, label: route.label }
}

export function addPageTab(tabs: PageTab[], tab: PageTab): PageTab[] {
  const existing = tabs.find((item) => item.path === tab.path)
  if (existing) {
    return existing.label === tab.label ? tabs : tabs.map((item) => (item.path === tab.path ? tab : item))
  }
  const next = [...tabs, tab]
  if (next.length <= MAX_OPEN_TABS) return next
  const removable = next.findIndex((item) => item.path !== PINNED_TAB_PATH)
  return removable < 0 ? next : next.filter((_, index) => index !== removable)
}

export function removePageTab(tabs: PageTab[], path: string): PageTab[] {
  if (path === PINNED_TAB_PATH) return tabs
  return tabs.filter((item) => item.path !== path)
}

export function restorePageTabs(storageKey: string, permissions: string[]): PageTab[] {
  const fallback = initialPageTabs(permissions)
  if (typeof window === 'undefined') return fallback
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(storageKey) ?? 'null') as unknown
    if (!Array.isArray(parsed)) return fallback
    const candidates: unknown[] = parsed
    const restored = candidates.flatMap((item): PageTab[] => {
      if (!item || typeof item !== 'object') return []
      const path = 'path' in item && typeof item.path === 'string' ? item.path : ''
      const route = getRouteByPath(path)
      return route && canAccessRoute(route, permissions) ? [{ path, label: route.label }] : []
    })
    const withoutPinned = restored.filter((tab) => tab.path !== PINNED_TAB_PATH)
    return [{ path: PINNED_TAB_PATH, label: '首页' }, ...withoutPinned]
  } catch {
    return fallback
  }
}

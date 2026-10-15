import { useEffect, useReducer } from 'react'
import {
  BellOutlined,
  CloseOutlined,
  DownOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import { Button, Dropdown, Layout, Tooltip } from 'antd'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { canAccessRoute, getRouteByPath, getTopNavigation } from '@/router/route-metadata'
import { useAuth } from '@/auth/use-auth'
import { addPageTab, PINNED_TAB_PATH, removePageTab, restorePageTabs, tabForRoute, type PageTab } from './page-tabs'
import './basic-layout.css'

const { Content } = Layout
const EMPTY_PERMISSIONS: string[] = []

type PageTabAction = { type: 'open'; tab: PageTab } | { type: 'close'; path: string }

function pageTabReducer(tabs: PageTab[], action: PageTabAction): PageTab[] {
  return action.type === 'open' ? addPageTab(tabs, action.tab) : removePageTab(tabs, action.path)
}

export default function BasicLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout, user } = useAuth()
  const permissions = user?.permissions ?? EMPTY_PERMISSIONS
  const activeRoute = getRouteByPath(location.pathname)
  const activePagePath = `${location.pathname}${location.search}`
  const topNavigation = getTopNavigation(permissions)
  const tabStorageKey = `erp:page-tabs:${user?.id ?? 'anonymous'}`
  const [pageTabs, dispatchPageTab] = useReducer(pageTabReducer, undefined, () =>
    restorePageTabs(tabStorageKey, permissions),
  )
  const availablePages = topNavigation.filter((item) => !pageTabs.some((tab) => tab.path === item.path))

  useEffect(() => {
    const tab = tabForRoute(location.pathname, activeRoute, location.search)
    if (tab && activeRoute && canAccessRoute(activeRoute, permissions)) dispatchPageTab({ type: 'open', tab })
  }, [activeRoute, location.pathname, location.search, permissions])

  useEffect(() => {
    window.sessionStorage.setItem(tabStorageKey, JSON.stringify(pageTabs))
  }, [pageTabs, tabStorageKey])

  const closePageTab = (path: string) => {
    if (path === PINNED_TAB_PATH) return
    const closingIndex = pageTabs.findIndex((tab) => tab.path === path)
    const remaining = removePageTab(pageTabs, path)
    if (activePagePath === path) {
      const nextTab = remaining[Math.min(closingIndex, remaining.length - 1)] ?? remaining[0]
      void navigate(nextTab?.path ?? PINNED_TAB_PATH)
    }
    dispatchPageTab({ type: 'close', path })
  }

  return (
    <Layout className="erp-layout">
      <header className="erp-topbar">
        <div className="erp-brand">
          <span className="erp-brand-mark">万</span>
          <strong>万矩环通科技有限公司</strong>
        </div>
        <nav aria-label="主导航" className="top-navigation">
          {topNavigation.map((item) => (
            <button
              className={
                location.pathname === item.path || location.pathname.startsWith(`${item.path}/`) ? 'active' : ''
              }
              key={item.key}
              onClick={() => void navigate(item.path)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="top-actions">
          <Tooltip title="搜索">
            <Button aria-label="搜索" icon={<SearchOutlined />} type="text" />
          </Tooltip>
          <Tooltip title="通知">
            <Button aria-label="通知" icon={<BellOutlined />} type="text" />
          </Tooltip>
          <Tooltip title="帮助">
            <Button aria-label="帮助" icon={<QuestionCircleOutlined />} type="text" />
          </Tooltip>
          <Dropdown menu={{ items: [{ key: 'logout', label: '退出登录', onClick: () => void logout() }] }}>
            <Button className="user-menu" type="text">
              {user?.name}
              <DownOutlined />
            </Button>
          </Dropdown>
        </div>
      </header>
      <nav aria-label="二级导航" className="secondary-navigation">
        <div aria-label="已打开页面" className="secondary-tabs" role="tablist">
          {pageTabs.map((tab) => (
            <div className={`page-tab${activePagePath === tab.path ? ' active' : ''}`} key={tab.path}>
              <button
                aria-selected={activePagePath === tab.path}
                className="page-tab-link"
                onClick={() => void navigate(tab.path)}
                role="tab"
                type="button"
              >
                {tab.label}
              </button>
              {tab.path !== PINNED_TAB_PATH && (
                <button
                  aria-label={`关闭${tab.label}`}
                  className="page-tab-close"
                  onClick={() => closePageTab(tab.path)}
                  type="button"
                >
                  <CloseOutlined />
                </button>
              )}
            </div>
          ))}
          <Dropdown
            menu={{
              items: availablePages.map((item) => ({
                key: item.key,
                label: item.label,
                onClick: () => void navigate(item.path),
              })),
            }}
            placement="bottomLeft"
          >
            <Button
              aria-label="添加页面"
              className="add-page"
              disabled={!availablePages.length}
              icon={<PlusOutlined />}
              type="text"
            />
          </Dropdown>
        </div>
        <span className="current-page">{activeRoute?.label}</span>
      </nav>
      <Content className="erp-content">
        <Outlet />
      </Content>
    </Layout>
  )
}

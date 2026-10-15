import type { ReactNode } from 'react'
import { matchPath } from 'react-router'
import ModulePlaceholderPage from '@/pages/common/module-placeholder-page'
import ForbiddenPage from '@/pages/error/forbidden-page'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { affiliateCenterRoutes } from '@/router/affiliate-center-routes'
import {
  BestsellersPage,
  DashboardPage,
  DataRolloutPage,
  FinanceOverviewPage,
  FinanceOrdersPage,
  FinancePaymentsPage,
  FinanceReconciliationPage,
  FinanceStatementDetailPage,
  FinanceStatementsPage,
  FinanceTransactionsPage,
  LogisticsPage,
  LogisticsStatusPage,
  LogisticsCarriersPage,
  LogisticsExceptionsPage,
  LogisticsPackageEditorPage,
  LogisticsReviewPage,
  LogisticsShippingPage,
  LogisticsTaskDetailPage,
  OrderDetailPage,
  OrderListPage,
  ProductDetailPage,
  ProductListPage,
  ReturnsPage,
  ReturnDetailPage,
  SettingDetailPage,
  SettingListPage,
} from '@/router/route-pages'

export interface AppRouteMetadata {
  key: string
  label: string
  path: string
  element: ReactNode
  permissions?: string[]
  showInTopNav?: boolean
}

export const appRouteMetadata: AppRouteMetadata[] = [
  { key: '/403', label: '无访问权限', path: '/403', element: <ForbiddenPage /> },
  { key: '/dashboard', label: '首页', path: '/dashboard', element: <DashboardPage />, permissions: ['dashboard:view'] },
  {
    key: '/products',
    label: '商品列表',
    path: '/products',
    element: <ProductListPage />,
    permissions: [modulePermissionCodes.productsView],
    showInTopNav: true,
  },
  {
    key: '/products/:productId',
    label: '商品详情',
    path: '/products/:productId',
    element: <ProductDetailPage />,
    permissions: [modulePermissionCodes.productsView],
  },
  {
    key: '/bestsellers',
    label: '畅销榜',
    path: '/bestsellers',
    element: <BestsellersPage />,
    permissions: [modulePermissionCodes.bestsellersView],
    showInTopNav: true,
  },
  ...affiliateCenterRoutes,
  {
    key: '/sales',
    label: '销售',
    path: '/sales',
    element: <ModulePlaceholderPage title="销售" />,
    permissions: ['sales:view'],
    showInTopNav: true,
  },
  {
    key: '/orders',
    label: '全部订单',
    path: '/orders',
    element: <OrderListPage />,
    permissions: [modulePermissionCodes.ordersView],
    showInTopNav: true,
  },
  {
    key: '/orders/:orderId',
    label: '订单详情',
    path: '/orders/:orderId',
    element: <OrderDetailPage />,
    permissions: [modulePermissionCodes.ordersView],
  },
  {
    key: '/ads',
    label: '广告',
    path: '/ads',
    element: <ModulePlaceholderPage title="广告" />,
    permissions: ['ads:view'],
    showInTopNav: true,
  },
  {
    key: '/platform-warehouse',
    label: '平台仓',
    path: '/platform-warehouse',
    element: <ModulePlaceholderPage title="平台仓" />,
    permissions: ['platform-warehouse:view'],
    showInTopNav: true,
  },
  {
    key: '/warehouse',
    label: '仓库',
    path: '/warehouse',
    element: <ModulePlaceholderPage title="库存" />,
    permissions: ['warehouse:view'],
    showInTopNav: true,
  },
  {
    key: '/logistics',
    label: '物流',
    path: '/logistics',
    element: <LogisticsPage />,
    permissions: [modulePermissionCodes.logisticsView],
    showInTopNav: true,
  },
  {
    key: '/logistics/exceptions',
    label: '物流异常中心',
    path: '/logistics/exceptions',
    element: <LogisticsExceptionsPage />,
    permissions: [modulePermissionCodes.logisticsView],
  },
  {
    key: '/logistics/carriers',
    label: '承运商管理',
    path: '/logistics/carriers',
    element: <LogisticsCarriersPage />,
    permissions: [modulePermissionCodes.logisticsView, modulePermissionCodes.logisticsManage],
  },
  {
    key: '/logistics/status',
    label: '物流状态',
    path: '/logistics/status',
    element: <LogisticsStatusPage />,
    permissions: [modulePermissionCodes.logisticsView],
  },
  {
    key: '/logistics/returns',
    label: '退换货',
    path: '/logistics/returns',
    element: <ReturnsPage />,
    permissions: [modulePermissionCodes.returnsView],
  },
  {
    key: '/logistics/returns/:requestId',
    label: '退换货详情',
    path: '/logistics/returns/:requestId',
    element: <ReturnDetailPage />,
    permissions: [modulePermissionCodes.returnsView],
  },
  {
    key: '/logistics/tasks/:taskId',
    label: '物流任务详情',
    path: '/logistics/tasks/:taskId',
    element: <LogisticsTaskDetailPage />,
    permissions: [modulePermissionCodes.logisticsView],
  },
  {
    key: '/logistics/tasks/:taskId/review',
    label: '订单复核',
    path: '/logistics/tasks/:taskId/review',
    element: <LogisticsReviewPage />,
    permissions: [modulePermissionCodes.logisticsView, modulePermissionCodes.logisticsOperate],
  },
  {
    key: '/logistics/tasks/:taskId/packages/new',
    label: '包裹编辑',
    path: '/logistics/tasks/:taskId/packages/new',
    element: <LogisticsPackageEditorPage />,
    permissions: [modulePermissionCodes.logisticsView, modulePermissionCodes.logisticsOperate],
  },
  {
    key: '/logistics/tasks/:taskId/shipping',
    label: '物流服务与运单',
    path: '/logistics/tasks/:taskId/shipping',
    element: <LogisticsShippingPage />,
    permissions: [modulePermissionCodes.logisticsView, modulePermissionCodes.logisticsDispatch],
  },
  {
    key: '/data',
    label: '数据',
    path: '/data',
    element: <DataRolloutPage />,
    permissions: ['data:view'],
    showInTopNav: true,
  },
  {
    key: '/finance',
    label: '财务',
    path: '/finance',
    element: <FinanceOverviewPage />,
    permissions: [modulePermissionCodes.financeView],
    showInTopNav: true,
  },
  {
    key: '/finance/orders',
    label: '订单财务',
    path: '/finance/orders',
    element: <FinanceOrdersPage />,
    permissions: [modulePermissionCodes.financeView],
  },
  {
    key: '/finance/statements',
    label: '财务结算单',
    path: '/finance/statements',
    element: <FinanceStatementsPage />,
    permissions: [modulePermissionCodes.financeView],
  },
  {
    key: '/finance/statements/:statementId',
    label: '结算单详情',
    path: '/finance/statements/:statementId',
    element: <FinanceStatementDetailPage />,
    permissions: [modulePermissionCodes.financeView],
  },
  {
    key: '/finance/transactions',
    label: '财务流水',
    path: '/finance/transactions',
    element: <FinanceTransactionsPage />,
    permissions: [modulePermissionCodes.financeView],
  },
  {
    key: '/finance/payments',
    label: '财务付款',
    path: '/finance/payments',
    element: <FinancePaymentsPage />,
    permissions: [modulePermissionCodes.financeView],
  },
  {
    key: '/finance/reconciliation',
    label: '财务对账',
    path: '/finance/reconciliation',
    element: <FinanceReconciliationPage />,
    permissions: [modulePermissionCodes.financeView],
  },
  {
    key: '/tools',
    label: '工具',
    path: '/tools',
    element: <ModulePlaceholderPage title="工具" />,
    permissions: ['tools:view'],
    showInTopNav: true,
  },
  {
    key: '/settings',
    label: '设置',
    path: '/settings',
    element: <SettingListPage />,
    permissions: ['settings:view'],
    showInTopNav: true,
  },
  {
    key: '/settings/:settingId',
    label: '设置详情',
    path: '/settings/:settingId',
    element: <SettingDetailPage />,
    permissions: ['settings:view'],
  },
]

export const secondaryNavigation = [
  { key: '/dashboard', label: '首页' },
  { key: '/orders', label: '全部订单' },
  { key: '/products', label: '商品列表' },
]

export function getRouteByPath(path: string) {
  return appRouteMetadata.find((route) => Boolean(matchPath({ path: route.path, end: true }, path)))
}

export function canAccessRoute(route: AppRouteMetadata, permissions: string[] = []) {
  return !route.permissions?.length || route.permissions.every((permission) => permissions.includes(permission))
}

export function getTopNavigation(permissions: string[] = []) {
  return appRouteMetadata.filter((route) => route.showInTopNav && canAccessRoute(route, permissions))
}

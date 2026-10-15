import { authSession } from '@/auth/auth-session'
import { modulePermissionCodes } from '@/auth/permission-codes'
import type { AuthApi, AuthUser, LoginPayload } from './auth-api'

interface MockAccount extends AuthUser {
  password: string
  accessToken: string
}

const accounts: MockAccount[] = [
  {
    id: '1',
    name: '系统管理员',
    username: 'admin',
    password: 'admin123',
    accessToken: 'mock-access-token-admin',
    roles: [{ id: 'role-1', code: 'admin', name: '系统管理员' }],
    permissions: [
      'dashboard:view',
      modulePermissionCodes.shopsView,
      modulePermissionCodes.shopsManage,
      modulePermissionCodes.productsView,
      modulePermissionCodes.bestsellersView,
      modulePermissionCodes.affiliateCenterView,
      'sales:view',
      modulePermissionCodes.ordersView,
      modulePermissionCodes.syncTrigger,
      'ads:view',
      'platform-warehouse:view',
      'warehouse:view',
      modulePermissionCodes.logisticsView,
      modulePermissionCodes.logisticsOperate,
      modulePermissionCodes.logisticsDispatch,
      modulePermissionCodes.logisticsManage,
      modulePermissionCodes.logisticsCostView,
      modulePermissionCodes.logisticsCostReconcile,
      modulePermissionCodes.returnsView,
      modulePermissionCodes.returnsManage,
      modulePermissionCodes.returnsInspect,
      'data:view',
      'finance:view',
      'tools:view',
      'settings:view',
    ],
  },
  {
    id: '2',
    name: '运营专员',
    username: 'operator',
    password: 'operator123',
    accessToken: 'mock-access-token-operator',
    roles: [{ id: 'role-2', code: 'operator', name: '运营角色' }],
    permissions: ['dashboard:view', modulePermissionCodes.productsView, modulePermissionCodes.ordersView],
  },
]

export const mockAuthApi: AuthApi = {
  async login({ username, password }: LoginPayload) {
    await new Promise((resolve) => window.setTimeout(resolve, 500))
    const account = accounts.find((item) => item.username === username && item.password === password)
    if (!account) throw new Error('用户名或密码错误')
    return { accessToken: account.accessToken }
  },
  async getCurrentUser() {
    await new Promise((resolve) => window.setTimeout(resolve, 150))
    const account = accounts.find((item) => item.accessToken === authSession.getAccessToken())
    if (!account) throw new Error('登录已失效')
    return {
      id: account.id,
      name: account.name,
      username: account.username,
      roles: account.roles,
      permissions: account.permissions,
    }
  },
  async logout() {},
}

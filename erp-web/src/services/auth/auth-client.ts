import { mockAuthApi } from './mock-auth-api'
import { request } from '@/services/http-client'
import { isFeatureMockEnabled } from '@/services/api-mode'
import type { AuthApi, AuthUser, LoginPayload, LoginResult } from './auth-api'

const httpAuthApi: AuthApi = {
  login: (payload: LoginPayload) => request<LoginResult>({ method: 'post', url: '/auth/login', data: payload }),
  getCurrentUser: () => request<AuthUser>({ method: 'get', url: '/auth/current-user' }),
  logout: () => request<void>({ method: 'post', url: '/auth/logout' }),
}

export const authApi = isFeatureMockEnabled('auth') ? mockAuthApi : httpAuthApi

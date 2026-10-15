export interface AuthUser {
  id: string
  name: string
  username: string
  roles: AuthRole[]
  permissions: string[]
}

export interface AuthRole {
  id: string
  code: string
  name: string
}

export interface LoginResult {
  accessToken: string
}

export interface LoginPayload {
  username: string
  password: string
}

export interface AuthApi {
  login(payload: LoginPayload): Promise<LoginResult>
  getCurrentUser(): Promise<AuthUser>
  logout(): Promise<void>
}

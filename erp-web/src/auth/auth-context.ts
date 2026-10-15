import { createContext } from 'react'
import type { AuthUser, LoginPayload } from '@/services/auth'

export interface AuthContextValue {
  user: AuthUser | null
  isAuthenticated: boolean
  hasPermissions: (permissions?: string[]) => boolean
  login: (payload: LoginPayload) => Promise<void>
  logout: () => void
  isInitializing: boolean
}

export const AuthContext = createContext<AuthContextValue | null>(null)

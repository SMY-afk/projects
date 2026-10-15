import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { AUTH_FORBIDDEN_EVENT, AUTH_UNAUTHORIZED_EVENT } from './auth-events'

export function AuthStatusRedirect() {
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    const redirectToForbidden = () => {
      void navigate('/403', { replace: true })
    }
    const redirectToLogin = () => {
      void navigate('/login', { replace: true, state: { from: location, sessionExpired: true } })
    }
    window.addEventListener(AUTH_FORBIDDEN_EVENT, redirectToForbidden)
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, redirectToLogin)
    return () => {
      window.removeEventListener(AUTH_FORBIDDEN_EVENT, redirectToForbidden)
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, redirectToLogin)
    }
  }, [location, navigate])

  return null
}

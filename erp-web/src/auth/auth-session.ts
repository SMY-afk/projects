const tokenStorageKey = 'erp-web.access-token'

/**
 * Authentication storage policy: only the short-lived access token is kept in
 * sessionStorage. User information, roles, and permissions are always loaded
 * from the current-user endpoint after the application starts.
 */
export const authSession = {
  getAccessToken: () => window.sessionStorage.getItem(tokenStorageKey),
  setAccessToken: (token: string) => window.sessionStorage.setItem(tokenStorageKey, token),
  clear: () => window.sessionStorage.removeItem(tokenStorageKey),
}

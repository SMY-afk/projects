import { expect, test } from '@playwright/test'

test.describe('session journey', () => {
  test('restores and signs out an isolated real session', async ({ page }) => {
    const accessToken = process.env.E2E_LOGOUT_ACCESS_TOKEN
    const username = process.env.E2E_USERNAME
    if (!accessToken || !username) throw new Error('E2E session scenario is missing')

    await page.goto('/login')
    await page.evaluate((token) => window.sessionStorage.setItem('erp-web.access-token', token), accessToken)

    const currentUserResponse = page.waitForResponse(
      (response) => response.url().includes('/api/auth/current-user') && response.request().method() === 'GET',
    )
    await page.goto('/orders')
    expect((await currentUserResponse).status()).toBe(200)
    await expect(page.locator('button.user-menu')).toContainText(username)
    expect(await page.evaluate(() => window.sessionStorage.getItem('erp-web.access-token') !== null)).toBe(true)

    const logoutResponse = page.waitForResponse(
      (response) => response.url().includes('/api/auth/logout') && response.request().method() === 'POST',
    )
    await page.locator('button.user-menu').click()
    await page.getByRole('menuitem', { name: '退出登录' }).click()
    expect((await logoutResponse).status()).toBe(204)

    await expect(page).toHaveURL(/\/login$/)
    expect(await page.evaluate(() => window.sessionStorage.getItem('erp-web.access-token'))).toBeNull()
    const restoredSession = await page.request.get('/api/auth/current-user', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    expect(restoredSession.status()).toBe(401)
  })
})

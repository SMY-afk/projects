import { expect, test } from '@playwright/test'

test.describe('order list journey', () => {
  test('authenticated user can open the seeded order detail', async ({ page }) => {
    const accessToken = process.env.E2E_ACCESS_TOKEN
    const seededOrderNumber = process.env.E2E_ORDER_NUMBER
    if (!accessToken) throw new Error('E2E_ACCESS_TOKEN is required')
    if (!seededOrderNumber) throw new Error('E2E_ORDER_NUMBER is required')
    await page.goto('/login')
    await page.evaluate((token) => window.sessionStorage.setItem('erp-web.access-token', token), accessToken)

    await page.goto('/orders')
    await expect(page.getByRole('heading', { name: '订单列表' })).toBeVisible()
    const seededRow = page.locator('.ant-table-tbody .ant-table-row').filter({ hasText: seededOrderNumber })
    await expect(seededRow).toHaveCount(1)
    const renderedOrderNumber = (await seededRow.locator('td').first().locator('.ant-typography').innerText()).trim()
    expect(renderedOrderNumber).toBe(seededOrderNumber)
    await expect(seededRow).toContainText('US$90.00')
    await seededRow.getByRole('button', { name: '详情' }).click()
    await expect(page).toHaveURL(/\/orders\/[^/]+$/)
    await expect(page.getByRole('heading', { name: seededOrderNumber })).toBeVisible()
  })
})

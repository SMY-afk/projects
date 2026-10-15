import { expect, test, type Page } from '@playwright/test'

const query = 'from=2026-08-23&to=2026-08-29&currency=USD'

const authenticate = async (page: Page, accessToken: string) => {
  await page.goto('/login')
  await page.evaluate((token) => window.sessionStorage.setItem('erp-web.access-token', token), accessToken)
}

test.describe('affiliate center real-data journey', () => {
  test('shows creator and video snapshots and opens creator detail', async ({ page }) => {
    const accessToken = process.env.E2E_ACCESS_TOKEN
    const shopId = process.env.E2E_SHOP_ID
    const creatorUsername = process.env.E2E_AFFILIATE_CREATOR_USERNAME
    if (!accessToken || !shopId || !creatorUsername) throw new Error('Affiliate Center E2E scenario is incomplete')
    await authenticate(page, accessToken)

    await page.goto(`/affiliate-center/creators?shopId=${shopId}&${query}`)
    await expect(page.getByRole('heading', { name: '联盟中心' })).toBeVisible()
    const creatorRow = page.locator('.ant-table-tbody .ant-table-row').filter({ hasText: creatorUsername })
    await expect(creatorRow).toHaveCount(1)
    await expect(creatorRow).toContainText('$123.45')

    await creatorRow.getByText(creatorUsername, { exact: true }).click()
    await expect(page).toHaveURL(/\/affiliate-center\/creators\/[^/?]+/)
    await expect(page.getByRole('heading', { name: creatorUsername })).toBeVisible()
    await expect(page.getByText('E2E Creator Detail Video')).toBeVisible()

    await page.goto(`/affiliate-center/videos?shopId=${shopId}&${query}`)
    await expect(page.getByRole('tab', { name: '所有视频' })).toHaveAttribute('aria-selected', 'true')
    const videoRow = page.locator('.ant-table-tbody .ant-table-row').filter({ hasText: 'E2E Affiliate Video' })
    await expect(videoRow).toHaveCount(1)
    await expect(videoRow).toContainText('$54.32')
  })
})

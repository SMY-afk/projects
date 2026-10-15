import { expect, test, type Page } from '@playwright/test'

const authenticate = async (page: Page, accessToken: string) => {
  await page.goto('/login')
  await page.evaluate((token) => window.sessionStorage.setItem('erp-web.access-token', token), accessToken)
}

test.describe('finance real-data journey', () => {
  test('opens overview, statement detail and the existing order detail', async ({ page }) => {
    const accessToken = process.env.E2E_ACCESS_TOKEN
    const statementNumber = process.env.E2E_STATEMENT_NUMBER
    const orderNumber = process.env.E2E_ORDER_NUMBER
    if (!accessToken || !statementNumber || !orderNumber) throw new Error('Finance E2E scenario is incomplete')
    await authenticate(page, accessToken)

    await page.goto('/finance')
    await expect(page.getByRole('heading', { name: '财务总览' })).toBeVisible()
    await expect(page.getByText('真实 API')).toHaveCount(0)
    await expect(page.getByLabel('财务店铺')).toBeVisible()
    await expect(page.getByText('数据部分完整')).toBeVisible()
    await expect(page.getByRole('table').getByText('已付款', { exact: true })).toBeVisible()
    await expect(page.getByRole('table').getByText('PAID', { exact: true })).toHaveCount(0)

    await page.getByRole('link', { name: '订单' }).click()
    await expect(page).toHaveURL(/\/finance\/orders$/)
    const orderRow = page.locator('.ant-table-tbody .ant-table-row').filter({ hasText: orderNumber })
    await expect(orderRow).toContainText('已经完结')
    await expect(
      page.getByRole('columnheader', { name: /^状态/ }).getByRole('button', { name: 'filter' }),
    ).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '金额类型' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '口径' })).toHaveCount(0)
    await expect(page.getByRole('columnheader', { name: '对应结算单' })).toHaveCount(0)
    await expect(page.getByRole('columnheader', { name: '流水号' })).toHaveCount(0)

    const filterByState = async (state: string) => {
      await page.getByRole('columnheader', { name: /^状态/ }).getByRole('button', { name: 'filter' }).click()
      const dropdown = page.locator('.ant-table-filter-dropdown')
      const expectedState = state === '已付款后退款' ? 'refunded' : 'completed'
      const filteredResponse = page.waitForResponse((response) => {
        const url = new URL(response.url())
        return (
          url.pathname.endsWith('/api/finance/transactions') && url.searchParams.get('paymentState') === expectedState
        )
      })
      await dropdown.getByText(state, { exact: true }).click()
      await dropdown.getByRole('button', { name: /确\s*定/ }).click()
      await filteredResponse
    }
    await filterByState('已付款后退款')
    await expect(page.locator('.ant-table-tbody')).toContainText('已付款后退款')
    await expect(page.locator('.ant-table-tbody')).not.toContainText('已经完结')

    await filterByState('已经完结')
    await expect(orderRow).toContainText('已经完结')
    await expect(page.locator('.ant-table-tbody')).not.toContainText('已付款后退款')

    await page.getByRole('link', { name: '结算单' }).click()
    await expect(page).toHaveURL(/\/finance\/statements$/)
    const statementRow = page.locator('.ant-table-tbody .ant-table-row').filter({ hasText: statementNumber })
    await expect(statementRow).toHaveCount(1)
    await expect(statementRow).toContainText('可用')
    await expect(statementRow).not.toContainText('available')
    await statementRow.getByRole('link', { name: statementNumber }).click()
    await expect(page.getByRole('heading', { name: '结算单详情' })).toBeVisible()
    await expect(page.getByText('结算单、流水和付款已匹配')).toBeVisible()

    await page.getByRole('link', { name: orderNumber }).click()
    await expect(page).toHaveURL(/\/orders\/[^/]+$/)
    await expect(page.getByRole('heading', { name: orderNumber })).toBeVisible()
  })

  test('shows payment masking, reconciliation issue and streams CSV', async ({ page }) => {
    const accessToken = process.env.E2E_ACCESS_TOKEN
    const paymentNumber = process.env.E2E_PAYMENT_NUMBER
    const shopId = process.env.E2E_SHOP_ID
    if (!accessToken || !paymentNumber || !shopId) throw new Error('Finance E2E scenario is incomplete')
    await authenticate(page, accessToken)

    await page.goto('/finance/payments')
    await expect(page.getByRole('heading', { name: '付款' })).toBeVisible()
    const paymentRow = page.locator('.ant-table-tbody .ant-table-row').filter({ hasText: paymentNumber })
    await expect(paymentRow).toContainText('****4321')

    await page.getByRole('link', { name: '对账' }).click()
    await expect(page.getByRole('heading', { name: '对账' })).toBeVisible()
    await expect(page.getByText('订单未关联').first()).toBeVisible()

    const exportResponse = await page.request.get(
      `/api/finance/export?resource=transactions&shopId=${shopId}&currency=USD`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
    expect(exportResponse.status()).toBe(200)
    expect(exportResponse.headers()['content-type']).toContain('text/csv')
    expect(await exportResponse.text()).toContain('e2e-transaction-')
  })

  test('enforces finance permission and tenant isolation through the real API', async ({ page }) => {
    const accessToken = process.env.E2E_ACCESS_TOKEN
    const restrictedToken = process.env.E2E_RESTRICTED_ACCESS_TOKEN
    if (!accessToken || !restrictedToken) throw new Error('Finance E2E permission scenario is incomplete')

    const forbidden = await page.request.get('/api/finance/overview', {
      headers: { Authorization: `Bearer ${restrictedToken}` },
    })
    expect(forbidden.status()).toBe(403)
    await authenticate(page, restrictedToken)
    await page.goto('/finance')
    await expect(page).toHaveURL(/\/403$/)
    await expect(page.getByRole('main').getByText('无访问权限')).toBeVisible()

    const foreignShopId = process.env.E2E_FOREIGN_SHOP_ID
    const foreignStatementId = process.env.E2E_FOREIGN_STATEMENT_ID
    if (!foreignShopId || !foreignStatementId) throw new Error('A second tenant Finance record is required')
    const foreignList = await page.request.get(`/api/finance/statements?page=1&pageSize=20&shopId=${foreignShopId}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    expect(foreignList.status()).toBe(200)
    expect((await foreignList.json()).total).toBe(0)
    const foreignDetail = await page.request.get(`/api/finance/statements/${foreignStatementId}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    expect(foreignDetail.status()).toBe(404)
  })
})

import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const apiRoot = path.resolve(projectRoot, '../erp-api')
const pythonPath = path.join(apiRoot, '.venv', 'Scripts', 'python.exe')
const sessionScript = path.join(projectRoot, 'tests', 'e2e', 'session_setup.py')

interface E2EScenario {
  accessToken: string
  logoutAccessToken: string
  restrictedAccessToken: string
  tenantId: string
  shopId: string
  orderId: string
  orderNumber: string
  statementId: string
  statementNumber: string
  paymentNumber: string
  foreignStatementId: string
  foreignShopId: string
  username: string
  affiliateCreatorId: string
  affiliateCreatorUsername: string
}

export default function globalSetup() {
  const scenario = JSON.parse(
    execFileSync(pythonPath, [sessionScript, 'create'], {
      cwd: apiRoot,
      encoding: 'utf8',
      windowsHide: true,
    }),
  ) as E2EScenario
  if (
    !scenario.accessToken ||
    !scenario.logoutAccessToken ||
    !scenario.restrictedAccessToken ||
    !scenario.tenantId ||
    !scenario.orderNumber ||
    !scenario.statementId ||
    !scenario.statementNumber ||
    !scenario.paymentNumber ||
    !scenario.affiliateCreatorId ||
    !scenario.affiliateCreatorUsername ||
    !scenario.username
  ) {
    throw new Error('Failed to create the isolated E2E scenario')
  }
  process.env.E2E_ACCESS_TOKEN = scenario.accessToken
  process.env.E2E_LOGOUT_ACCESS_TOKEN = scenario.logoutAccessToken
  process.env.E2E_RESTRICTED_ACCESS_TOKEN = scenario.restrictedAccessToken
  process.env.E2E_ORDER_NUMBER = scenario.orderNumber
  process.env.E2E_SHOP_ID = scenario.shopId
  process.env.E2E_STATEMENT_ID = scenario.statementId
  process.env.E2E_STATEMENT_NUMBER = scenario.statementNumber
  process.env.E2E_PAYMENT_NUMBER = scenario.paymentNumber
  process.env.E2E_FOREIGN_STATEMENT_ID = scenario.foreignStatementId
  process.env.E2E_FOREIGN_SHOP_ID = scenario.foreignShopId
  process.env.E2E_USERNAME = scenario.username
  process.env.E2E_AFFILIATE_CREATOR_ID = scenario.affiliateCreatorId
  process.env.E2E_AFFILIATE_CREATOR_USERNAME = scenario.affiliateCreatorUsername

  return () => {
    execFileSync(pythonPath, [sessionScript, 'cleanup'], {
      cwd: apiRoot,
      input: JSON.stringify(scenario),
      windowsHide: true,
    })
  }
}

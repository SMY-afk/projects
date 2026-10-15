import { Button, Space } from 'antd'
import { Link, useLocation } from 'react-router'

const items = [
  { path: '/finance', label: '总览', exact: true },
  { path: '/finance/orders', label: '订单' },
  { path: '/finance/statements', label: '结算单' },
  { path: '/finance/transactions', label: '流水' },
  { path: '/finance/payments', label: '付款' },
  { path: '/finance/reconciliation', label: '对账' },
]

export function FinanceSectionNav() {
  const { pathname } = useLocation()
  return (
    <nav className="finance-section-nav" aria-label="财务模块导航">
      <Space wrap>
        {items.map((item) => {
          const active = item.exact ? pathname === item.path : pathname.startsWith(item.path)
          return (
            <Link key={item.path} to={item.path}>
              <Button type={active ? 'primary' : 'text'}>{item.label}</Button>
            </Link>
          )
        })}
      </Space>
    </nav>
  )
}

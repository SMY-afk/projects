import { useMemo, useState } from 'react'
import dayjs from 'dayjs'
import { useFinanceShopsQuery } from '../queries/finance.queries'
import { defaultFinanceRange, resolveFinanceRange } from '../utils/finance-range'

export function useFinanceListScope() {
  const shopsQuery = useFinanceShopsQuery()
  const shops = shopsQuery.data ?? []
  const [shopId, setShopId] = useState<string>()
  const [currency, setCurrency] = useState('USD')
  const [range, setRange] = useState(() => defaultFinanceRange('UTC'))
  const selectedShopId = shopId ?? shops[0]?.id
  const selectedShop = shops.find((shop) => shop.id === selectedShopId)
  const timezone = selectedShop?.timezone || 'UTC'
  const window = useMemo(() => resolveFinanceRange(range, timezone), [range, timezone])
  return {
    shopsQuery,
    shops,
    selectedShopId,
    timezone,
    range,
    currency,
    window,
    maxDate: dayjs().tz(timezone).startOf('day'),
    setShopId,
    setRange,
    setCurrency,
  }
}

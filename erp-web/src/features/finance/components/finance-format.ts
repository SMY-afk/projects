const safeCurrency = (currency?: string) => currency?.trim().toUpperCase() || 'USD'

export function financeCurrencyDigits(currency: string) {
  try {
    return (
      new Intl.NumberFormat('zh-CN', { style: 'currency', currency: safeCurrency(currency) }).resolvedOptions()
        .maximumFractionDigits ?? 2
    )
  } catch {
    return 2
  }
}

export function financeMajorAmount(amountMinor: number, currency: string) {
  return amountMinor / 10 ** financeCurrencyDigits(currency)
}

export function formatFinanceMoney(amountMinor: number | null | undefined, currency: string) {
  if (amountMinor === null || amountMinor === undefined) return '--'
  const normalizedCurrency = safeCurrency(currency)
  try {
    return new Intl.NumberFormat('zh-CN', {
      style: 'currency',
      currency: normalizedCurrency,
    }).format(financeMajorAmount(amountMinor, normalizedCurrency))
  } catch {
    return `${normalizedCurrency} ${financeMajorAmount(amountMinor, normalizedCurrency).toFixed(2)}`
  }
}

export function formatFinanceTime(value: string | null | undefined, timezone?: string | null) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: timezone || 'UTC',
    }).formatToParts(date)
    const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? '--'
    return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`
  } catch {
    return '--'
  }
}

export function formatFinanceDate(value: string | null | undefined, timezone?: string | null) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  try {
    const parts = new Intl.DateTimeFormat('en-CA', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      timeZone: timezone || 'UTC',
    }).formatToParts(date)
    const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? '--'
    return `${part('year')}-${part('month')}-${part('day')}`
  } catch {
    return '--'
  }
}

export function formatFinanceAxis(amountMinor: number, currency: string) {
  const value = financeMajorAmount(amountMinor, currency)
  const prefix = currency === 'USD' ? '$' : `${currency} `
  if (Math.abs(value) >= 1_000_000) return `${prefix}${(value / 1_000_000).toFixed(1)}M`
  if (Math.abs(value) >= 1_000) return `${prefix}${(value / 1_000).toFixed(1)}K`
  return `${prefix}${Math.round(value)}`
}

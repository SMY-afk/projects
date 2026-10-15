import dayjs from 'dayjs'

export const formatMoney = (value: number | null | undefined, currency = 'USD') =>
  value == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(value / 100)

export const formatCount = (value: number | string | null | undefined) =>
  value == null ? '—' : Number(value).toLocaleString()

export const formatRatio = (value: string | null | undefined) =>
  value == null ? '—' : `${(Number(value) * 100).toFixed(2)}%`

export const formatDateTime = (value: string | null | undefined) =>
  value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '—'

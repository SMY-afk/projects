const messages: Record<string, string> = {
  invalid_response: '平台返回格式无效，未写入本地数据。',
  missing_field: '平台返回字段不完整，未写入本地数据。',
  platform_error: '平台请求未成功，请稍后重新同步。',
  rate_limited: 'TikTok 正在限流，请稍后重新同步。',
  timeout: 'TikTok 响应超时，请稍后重新同步。',
  transport_error: '平台连接失败，请稍后重新同步。',
}

export const syncErrorMessage = (category: string | null, summary: string | null) =>
  (category && messages[category]) || summary || '—'

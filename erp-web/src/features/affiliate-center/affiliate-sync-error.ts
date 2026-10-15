import { HttpError } from '@/services/http-client'
import type { AffiliateCenterResource } from './types/affiliate-center.types'

const resourceLabel = (resource: AffiliateCenterResource) => (resource === 'creators' ? '联盟达人' : '所有视频')

export function getAffiliateSyncErrorMessage(
  resource: AffiliateCenterResource,
  error: unknown,
  captureProvider = 'HubStudio/CDP 浏览器',
): string {
  const prefix = `同步${resourceLabel(resource)}请求失败`
  if (!(error instanceof HttpError)) return `${prefix}，请稍后重试。`

  const availableDay = error.message.match(/available through (\d{4}-\d{2}-\d{2})/i)?.[1]
  if (error.status === 422 && availableDay) {
    const dataLabel = resource === 'creators' ? '达人' : '视频'
    return `TikTok ${dataLabel}数据目前可同步至 ${availableDay}，请调整结束日期后重试。`
  }
  if (error.status === 422) return `${prefix}：${error.message}`
  if (error.status === 403) return `${prefix}：当前账号没有该店铺的同步权限。`
  if (error.status === 503) return `${prefix}。请确认 ${captureProvider} 已登录且对应店铺监听在线。`
  if (error.kind === 'network' || error.kind === 'timeout') return `${prefix}：${error.message}`
  return `${prefix}：${error.message}`
}

export function isAffiliateAvailabilityErrorResolved(
  message: string,
  selectedEnd: string,
  latestAvailableDay?: string,
): boolean {
  if (!message.match(/目前可同步至 \d{4}-\d{2}-\d{2}/)) return false
  return Boolean(latestAvailableDay && selectedEnd <= latestAvailableDay)
}

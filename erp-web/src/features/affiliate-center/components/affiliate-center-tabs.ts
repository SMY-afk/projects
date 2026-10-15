import type { AffiliateCenterResource } from '../types/affiliate-center.types'

export type AffiliateCenterTab = AffiliateCenterResource | 'live-accounts'

export const affiliateCenterTabs = [
  { key: 'creators', label: '达人' },
  { key: 'videos', label: '所有视频' },
  { key: 'live-accounts', label: '联盟账号直播数据' },
] satisfies Array<{ key: AffiliateCenterTab; label: string }>

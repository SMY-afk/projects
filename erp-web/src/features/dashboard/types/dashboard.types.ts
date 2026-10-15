export type RealtimeRange = 'today' | 'last24h'
export type TrendRange = 'last7d' | 'last30d' | 'lastMonth' | 'year'
export type OrderRange = 'last7d' | 'last14d' | 'last28d'
export type DistributionMetric = 'salesVolume' | 'orderCount' | 'salesAmountMinor'

export interface DashboardQueryParams {
  platform?: string
  site?: string
  shopId?: string
  currency: string
  timezone: string
  realtimeRange: RealtimeRange
  trendRange: TrendRange
  orderRange: OrderRange
}

export interface DashboardSummary {
  salesVolume: number
  orderCount: number
  salesAmountMinor: number
  netSalesAmountMinor: number
  averageItemPriceMinor: number
  cancelledOrderCount: number
}

export interface DashboardShopOption {
  id: string
  name: string
  platform: string
  site?: string | null
  currency?: string | null
  timezone?: string | null
}

export interface DashboardDistributionItem {
  key: string
  orderCount: number
  salesVolume: number
  salesAmountMinor: number
}

export interface DashboardTrendPoint {
  date: string
  orderCount: number
  salesVolume: number
  salesAmountMinor: number
  netSalesAmountMinor: number
}

export interface DashboardProductPerformance {
  name: string
  sku: string
  productId: string
  platform: string
  store: string
  imageUrl?: string | null
  salesVolume: number
  salesAmountMinor: number
  netSalesAmountMinor: number
}

export interface DashboardSampleFunnel {
  scope: 'current_projection_all_time'
  applicationCount: number
  approvedCount: number
  shippedCount: number
  completedCount: number
  cancelledCount: number
  sourceObservedAt: string | null
}

export interface DashboardCreatorLevel {
  level: 'L0' | 'L1' | 'L2' | 'L3' | 'L4' | 'L5' | 'L6' | 'L7'
  count: number
  share: number
}

export interface DashboardCreatorEfficiencyRow {
  id: string
  rank: number
  username: string
  avatarUrl: string | null
  shopName: string
  videoCount: number
  gmvMinor: number
  gmvPerVideoMinor: number
  sampleStatus: string | null
  cumulativeGmvShare: number
}

export interface DashboardParetoPoint {
  id: string
  username: string
  shopName: string
  gmvMinor: number
  cumulativeGmvShare: number
}

export interface DashboardAffiliateOperations {
  sampleFunnel: DashboardSampleFunnel
  creatorLevels: DashboardCreatorLevel[]
  creatorEfficiency: {
    period: { start: string; end: string } | null
    complete: boolean
    shopCount: number
    totalCreators: number
    totalGmvMinor: number
    rows: DashboardCreatorEfficiencyRow[]
    pareto: DashboardParetoPoint[]
  }
}

export interface DashboardSnapshot {
  generatedAt: string
  filters: {
    platforms: string[]
    sites: string[]
    shops: DashboardShopOption[]
    currencies: string[]
  }
  selection: DashboardQueryParams
  realtime: {
    period: { start: string; end: string }
    current: DashboardSummary
    previous: DashboardSummary
    lastWeek: DashboardSummary
  }
  trend: {
    period: { start: string; end: string }
    current: DashboardSummary
    previous: DashboardSummary
    lastYear: DashboardSummary
    points: DashboardTrendPoint[]
  }
  fulfilmentMetrics: Array<{ label: string; value: number }>
  salesDistribution: DashboardDistributionItem[]
  orderDistribution: DashboardDistributionItem[]
  productPerformance: DashboardProductPerformance[]
  affiliateOperations?: DashboardAffiliateOperations
  netSalesEstimated: boolean
}

export type DashboardRankingDays = 7 | 30 | 90

export interface DashboardTopVideo {
  id: string
  videoId: string
  shopName: string
  creatorUsername: string | null
  title: string | null
  coverImageUrl: string | null
  videoPostTime: string | null
  gmvMinor: number
  views: number | null
}

export interface DashboardTopProduct {
  id: string
  productId: string
  shopName: string
  title: string | null
  coverImageUrl: string | null
  videoCount: number
  singleProductVideoGmvMinor: number | null
  singleProductVideoItemsSold: number | null
}

export interface DashboardAffiliateRankings {
  period: { start: string; end: string } | null
  days: DashboardRankingDays
  complete: boolean
  shopCount: number
  expectedShopCount: number
  totalVideos: number
  totalProducts: number
  topVideos: DashboardTopVideo[]
  topProducts: DashboardTopProduct[]
  productMetricScope: 'single_product_videos_only'
}

import type { DashboardAffiliateOperations } from '../types/dashboard.types'

export const emptyAffiliateOperations: DashboardAffiliateOperations = {
  sampleFunnel: {
    scope: 'current_projection_all_time',
    applicationCount: 0,
    approvedCount: 0,
    shippedCount: 0,
    completedCount: 0,
    cancelledCount: 0,
    sourceObservedAt: null,
  },
  creatorLevels: [],
  creatorEfficiency: {
    period: null,
    complete: false,
    shopCount: 0,
    totalCreators: 0,
    totalGmvMinor: 0,
    rows: [],
    pareto: [],
  },
}

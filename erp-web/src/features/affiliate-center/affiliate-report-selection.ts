import type { AffiliateCreatorReport } from './types/affiliate-center.types'

export function selectLatestCompleteReport(reports: AffiliateCreatorReport[]) {
  return reports.find((report) => report.status === 'complete')
}

import { describe, expect, it } from 'vitest'
import { selectLatestCompleteReport } from './affiliate-report-selection'
import type { AffiliateCreatorReport } from './types/affiliate-center.types'

function report(id: string, status: AffiliateCreatorReport['status']) {
  return { id, status } as AffiliateCreatorReport
}

describe('affiliate report selection', () => {
  it('keeps the previous complete snapshot when the newest run is partial', () => {
    expect(
      selectLatestCompleteReport([report('partial-new', 'partial'), report('complete-previous', 'complete')])?.id,
    ).toBe('complete-previous')
  })
})

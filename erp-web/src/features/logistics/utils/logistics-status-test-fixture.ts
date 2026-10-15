import type { LogisticsStatusLive } from '../types/logistics-status.types'

export const liveFixture: LogisticsStatusLive = {
  orderId: 'order-1',
  trackingStatus: 'delivered',
  checkedAt: '2026-10-12T05:50:50Z',
  platformStatus: 'COMPLETED',
  platformUpdatedAt: '2026-10-12T01:00:00Z',
  orderCreatedAt: '2026-10-07T08:52:41Z',
  shippedAt: '2026-10-07T08:52:41Z',
  firstLocationAt: '2026-10-09T07:00:00Z',
  deliveredAt: '2026-10-10T17:04:00Z',
  firstLocationDescription: "Arrived at the CITY OF INDUSTRY CA DISTRIBUTION CENTER carrier's facility.",
  shippedDescription: 'Order placed.',
  deliveredDescription: 'Delivered, Front Desk/Reception/Mail Room',
  milestoneNotes: [],
  events: [],
  packages: [],
}

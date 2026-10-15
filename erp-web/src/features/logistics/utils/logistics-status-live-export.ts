import type { LogisticsStatusLive, LogisticsStatusOrder } from '../types/logistics-status.types'

export interface ExportProgress {
  completed: number
  total: number
  failed: number
}
export interface LiveExportResult {
  liveByOrder: Record<string, LogisticsStatusLive>
  failures: Record<string, string>
}

export async function queryLiveExport(
  orders: LogisticsStatusOrder[],
  refresh: (id: string, signal: AbortSignal) => Promise<LogisticsStatusLive>,
  signal: AbortSignal,
  onProgress: (progress: ExportProgress) => void,
): Promise<LiveExportResult> {
  const result: LiveExportResult = { liveByOrder: {}, failures: {} }
  let nextIndex = 0
  let completed = 0
  let failed = 0
  onProgress({ completed, total: orders.length, failed })
  const worker = async () => {
    while (nextIndex < orders.length) {
      signal.throwIfAborted()
      const order = orders[nextIndex++]
      try {
        const live = await refresh(order.id, signal)
        if (live.orderId !== order.id) throw new Error('Order identity mismatch')
        signal.throwIfAborted()
        result.liveByOrder[order.id] = live
      } catch {
        signal.throwIfAborted()
        result.failures[order.id] = '官方实时查询失败，请重新查询该订单'
        failed += 1
      }
      completed += 1
      onProgress({ completed, total: orders.length, failed })
    }
  }
  await Promise.all(Array.from({ length: Math.min(3, orders.length) }, worker))
  signal.throwIfAborted()
  return result
}

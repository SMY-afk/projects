import { QueryClient } from '@tanstack/react-query'
import { HttpError } from '@/services/http-client'

const QUERY_STALE_TIME = 5 * 60 * 1000
const QUERY_GC_TIME = 30 * 60 * 1000

const shouldRetry = (failureCount: number, error: Error) => {
  if (error instanceof HttpError && error.kind === 'cancelled') return false
  if (error instanceof HttpError && error.status !== undefined && error.status >= 400 && error.status < 500) {
    return false
  }
  return failureCount < 2
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: QUERY_STALE_TIME,
      gcTime: QUERY_GC_TIME,
      retry: shouldRetry,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30_000),
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
})

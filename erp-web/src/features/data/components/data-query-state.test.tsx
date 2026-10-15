import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HttpError } from '@/services/http-client'
import { DataQueryState } from './data-query-state'

const envelope = (data: number[], isStale = false) => ({
  apiVersion: 'v1' as const,
  source: 'local_snapshot' as const,
  data,
  freshness: { isStale },
  errors: [],
})

describe('DataQueryState', () => {
  it('renders loading, empty, and stale states without fabricating data', () => {
    const { rerender } = render(
      <DataQueryState query={{ isLoading: true, isError: false }} emptyText="暂无快照">
        {() => <>数据</>}
      </DataQueryState>,
    )
    expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument()

    rerender(
      <DataQueryState query={{ data: envelope([]), isLoading: false, isError: false }} emptyText="暂无快照">
        {() => <>数据</>}
      </DataQueryState>,
    )
    expect(screen.getByText('暂无快照')).toBeInTheDocument()

    rerender(
      <DataQueryState query={{ data: envelope([], true), isLoading: false, isError: false }} emptyText="暂无快照">
        {() => <>数据</>}
      </DataQueryState>,
    )
    expect(screen.getByText('本地数据暂不可用')).toBeInTheDocument()
  })

  it('turns authentication, authorization, rate-limit, and timeout errors into clear states', () => {
    const { rerender } = render(
      <DataQueryState
        query={{ error: new HttpError('expired', { status: 401 }), isLoading: false, isError: true }}
        emptyText="暂无快照"
      >
        {() => <>数据</>}
      </DataQueryState>,
    )
    expect(screen.getByText('登录已失效')).toBeInTheDocument()

    rerender(
      <DataQueryState
        query={{ error: new HttpError('forbidden', { status: 403 }), isLoading: false, isError: true }}
        emptyText="暂无快照"
      >
        {() => <>数据</>}
      </DataQueryState>,
    )
    expect(screen.getByText('无访问权限')).toBeInTheDocument()

    rerender(
      <DataQueryState
        query={{ error: new HttpError('rate limited', { status: 429 }), isLoading: false, isError: true }}
        emptyText="暂无快照"
      >
        {() => <>数据</>}
      </DataQueryState>,
    )
    expect(screen.getByText('TikTok 正在限流')).toBeInTheDocument()

    rerender(
      <DataQueryState
        query={{ error: new HttpError('raw upstream error', { kind: 'timeout' }), isLoading: false, isError: true }}
        emptyText="暂无快照"
      >
        {() => <>数据</>}
      </DataQueryState>,
    )
    expect(screen.getByText('数据请求超时')).toBeInTheDocument()
    expect(screen.queryByText('raw upstream error')).not.toBeInTheDocument()
  })
})

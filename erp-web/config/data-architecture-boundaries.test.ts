import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const document = readFileSync(
  resolve(process.cwd(), 'docs/tiktok-shop/data-phase-gates-and-connector-boundary.md'),
  'utf8',
)

describe('data architecture boundaries', () => {
  it('keeps advanced features behind the stability gate', () => {
    expect(document).toContain('连续 14 天')
    expect(document).toContain('小时级实时数据')
    expect(document).toContain('更多视频字段')
    expect(document).toContain('直播商品明细')
    expect(document).toContain('广告归因')
    expect(document).toContain('导出功能')
  })

  it('separates TikTok Business or creator authorization and storage', () => {
    expect(document).toContain('TikTok Business/创作者数据连接器')
    expect(document).toContain('独立 OAuth')
    expect(document).toContain('不得复用 TikTok Shop Seller access token')
    expect(document).toContain('不得直接写入 TikTok Shop Analytics 业务表')
  })
})

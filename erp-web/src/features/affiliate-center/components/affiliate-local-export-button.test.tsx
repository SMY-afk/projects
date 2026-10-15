import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HttpError } from '@/services/http-client'
import { AffiliateLocalExportButton } from './affiliate-local-export-button'

const exportLocalMock = vi.hoisted(() => vi.fn())
const exportFeishuMock = vi.hoisted(() => vi.fn())

vi.mock('../api/affiliate-center.api', () => ({
  affiliateCenterApi: { exportLocal: exportLocalMock, exportFeishu: exportFeishuMock },
}))

describe('AffiliateLocalExportButton', () => {
  afterEach(() => {
    exportLocalMock.mockReset()
    exportFeishuMock.mockReset()
    vi.restoreAllMocks()
  })

  it('downloads the authenticated local export without reading credentials', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:local-export')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    exportLocalMock.mockResolvedValue({
      blob: new Blob(['{}'], { type: 'application/json' }),
      fileName: 'affiliate-export.json',
    })
    render(<AffiliateLocalExportButton from="2026-07-03" to="2026-09-03" />)

    fireEvent.click(screen.getByRole('button', { name: '导出五店三板块 JSON' }))

    await waitFor(() => expect(exportLocalMock).toHaveBeenCalledWith('2026-07-03', '2026-09-03'))
    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:local-export')
  })

  it('downloads only the two allowlisted Feishu views', async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:feishu-export')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    exportFeishuMock.mockResolvedValue({
      blob: new Blob(['{}'], { type: 'application/json' }),
      fileName: 'feishu-creators.json',
    })
    render(<AffiliateLocalExportButton from="" to="" disabled />)

    fireEvent.click(screen.getByRole('button', { name: '导出童车和遥控车飞书 JSON' }))

    await waitFor(() => expect(exportFeishuMock).toHaveBeenCalledOnce())
    expect(click).toHaveBeenCalledOnce()
  })

  it('shows the shop, module, and missing dates returned by ERP', async () => {
    const message = '本土店的视频数据不完整：缺失日期 2026-07-09、2026-07-10。'
    exportLocalMock.mockRejectedValue(new HttpError(message, { status: 409, code: 'affiliate_snapshot_incomplete' }))
    render(<AffiliateLocalExportButton from="2026-07-08" to="2026-09-05" />)

    fireEvent.click(screen.getByRole('button', { name: '导出五店三板块 JSON' }))

    expect(await screen.findByText(message)).toBeInTheDocument()
  })
})

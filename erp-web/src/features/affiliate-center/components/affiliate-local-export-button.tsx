import { DownloadOutlined } from '@ant-design/icons'
import { Button, Space, Typography } from 'antd'
import { useState } from 'react'
import { HttpError } from '@/services/http-client'
import { affiliateCenterApi } from '../api/affiliate-center.api'

interface AffiliateLocalExportButtonProps {
  from: string
  to: string
  disabled?: boolean
}

export function AffiliateLocalExportButton({ from, to, disabled }: AffiliateLocalExportButtonProps) {
  const [exporting, setExporting] = useState<'erp' | 'feishu'>()
  const [error, setError] = useState<string>()

  const download = async (source: 'erp' | 'feishu') => {
    setExporting(source)
    setError(undefined)
    try {
      const result =
        source === 'erp' ? await affiliateCenterApi.exportLocal(from, to) : await affiliateCenterApi.exportFeishu()
      const url = URL.createObjectURL(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download =
        result.fileName ?? (source === 'erp' ? `affiliate-center-${from}-to-${to}.json` : 'feishu-creators.json')
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (reason) {
      setError(
        reason instanceof HttpError && reason.message
          ? reason.message
          : source === 'erp'
            ? 'ERP 导出失败，请确认后端运行在本机、登录仍有效且五个店铺数据完整。'
            : '飞书导出失败，请确认应用配置、权限及两张表的访问授权。',
      )
    } finally {
      setExporting(undefined)
    }
  }

  return (
    <Space orientation="vertical" align="end" size={0}>
      <Space wrap>
        <Button
          aria-label="导出童车和遥控车飞书 JSON"
          icon={<DownloadOutlined />}
          loading={exporting === 'feishu'}
          onClick={() => void download('feishu')}
        >
          导出飞书两表
        </Button>
        <Button
          aria-label="导出五店三板块 JSON"
          disabled={disabled || !from || !to}
          icon={<DownloadOutlined />}
          loading={exporting === 'erp'}
          onClick={() => void download('erp')}
        >
          导出五店三板块
        </Button>
      </Space>
      {error && <Typography.Text type="danger">{error}</Typography.Text>}
    </Space>
  )
}

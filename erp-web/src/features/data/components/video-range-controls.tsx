import { ReloadOutlined } from '@ant-design/icons'
import { Button, DatePicker, Segmented, Space, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import type { VideoRangePreset } from '../types/data.types'
import { isVideoCustomDateDisabled } from '../utils/video-range'

const options = [
  { label: '今天', value: 'today' },
  { label: '最近7天', value: 'last7d' },
  { label: '最近30天', value: 'last30d' },
  { label: '自定义时间', value: 'custom' },
]

export function VideoRangeControls({
  preset,
  customRange,
  maxDate,
  canRefresh,
  refreshing,
  onPresetChange,
  onCustomRangeChange,
  onRefresh,
}: {
  preset: VideoRangePreset
  customRange: [Dayjs, Dayjs]
  maxDate: Dayjs
  canRefresh: boolean
  refreshing: boolean
  onPresetChange: (preset: VideoRangePreset) => void
  onCustomRangeChange: (range: [Dayjs, Dayjs]) => void
  onRefresh: () => void
}) {
  return (
    <Space className="data-video-range-controls" wrap>
      <Segmented
        aria-label="视频数据时间"
        value={preset}
        options={options}
        onChange={(value) => onPresetChange(value as VideoRangePreset)}
      />
      {preset === 'custom' && (
        <Space orientation="vertical" size={0}>
          <DatePicker.RangePicker
            aria-label="视频自定义时间"
            allowClear={false}
            maxDate={maxDate}
            value={customRange}
            disabledDate={(current, info) => isVideoCustomDateDisabled(current, info.from, maxDate)}
            onChange={(value) => value?.[0] && value[1] && onCustomRangeChange([value[0], value[1]])}
          />
          <Typography.Text className="data-video-range-hint" type="secondary">
            自定义时间最多选择 30 个自然日，且不能包含未来日期
          </Typography.Text>
        </Space>
      )}
      {canRefresh && (
        <Button icon={<ReloadOutlined />} loading={refreshing} onClick={onRefresh}>
          刷新视频数据
        </Button>
      )}
    </Space>
  )
}

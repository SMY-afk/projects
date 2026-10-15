import { Steps, Tag } from 'antd'
import type { LogisticsTaskStatus } from '../types/logistics.types'
import { getLogisticsStatusPresentation, LOGISTICS_STATUS_STEPS } from './logistics-status'

interface LogisticsStatusStepsProps {
  status: LogisticsTaskStatus
}

export function LogisticsStatusSteps({ status }: LogisticsStatusStepsProps) {
  const presentation = getLogisticsStatusPresentation(status)
  return (
    <div className="logistics-status-steps">
      <Tag color={presentation.stepStatus === 'error' ? 'error' : 'blue'}>{presentation.label}</Tag>
      <Steps
        current={presentation.current}
        items={LOGISTICS_STATUS_STEPS.map(({ title }) => ({ title }))}
        responsive
        size="small"
        status={presentation.stepStatus}
      />
    </div>
  )
}

import { dataRolloutConfig } from '../config/data-rollout'
import DataPage from './data-page'
import DataUnavailablePage from './data-unavailable-page'

export default function DataRolloutPage() {
  if (dataRolloutConfig.stage === 'placeholder') {
    return (
      <DataUnavailablePage description="数据模块已切回旧占位页，真实同步与数据展示暂时关闭。" title="数据模块已回滚" />
    )
  }
  return <DataPage rollout={dataRolloutConfig} />
}

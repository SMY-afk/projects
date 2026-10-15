import { Spin } from 'antd'

import './page-state.css'

interface PageLoadingProps {
  fullscreen?: boolean
  tip?: string
}

export default function PageLoading({ fullscreen = false, tip = '正在加载…' }: PageLoadingProps) {
  return (
    <div className={fullscreen ? 'page-loading page-loading-fullscreen' : 'page-loading'}>
      <Spin description={tip} />
    </div>
  )
}

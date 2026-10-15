import { Component, type ErrorInfo, type ReactNode } from 'react'
import { captureError } from './observability'

interface Props {
  children: ReactNode
}
interface State {
  hasError: boolean
}

export class ObservabilityErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    captureError(error, { source: 'react', componentStack: errorInfo.componentStack })
  }

  render() {
    return this.state.hasError ? <div role="alert">页面加载失败，请刷新后重试。</div> : this.props.children
  }
}

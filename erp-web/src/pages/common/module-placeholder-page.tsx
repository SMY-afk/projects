import { Empty } from 'antd'

interface ModulePlaceholderPageProps {
  title: string
}

export default function ModulePlaceholderPage({ title }: ModulePlaceholderPageProps) {
  return <Empty description={`${title}模块正在建设中`} />
}

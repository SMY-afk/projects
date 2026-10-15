import { Empty } from 'antd'

interface PageEmptyProps {
  description?: string
}

export default function PageEmpty({ description = '暂无数据' }: PageEmptyProps) {
  return <Empty className="page-empty" description={description} />
}

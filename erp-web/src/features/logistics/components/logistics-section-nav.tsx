import { Menu } from 'antd'
import { useLocation, useNavigate } from 'react-router'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { useAuth } from '@/auth/use-auth'

const sections = [
  {
    key: '/logistics/exceptions',
    label: '异常中心',
    permissions: [modulePermissionCodes.logisticsView],
  },
  {
    key: '/logistics',
    label: '任务中心',
    permissions: [modulePermissionCodes.logisticsView],
  },
  {
    key: '/logistics/status',
    label: '物流状态',
    permissions: [modulePermissionCodes.logisticsView],
  },
  {
    key: '/logistics/returns',
    label: '退换货',
    permissions: [modulePermissionCodes.returnsView],
  },
  {
    key: '/logistics/carriers',
    label: '承运商管理',
    permissions: [modulePermissionCodes.logisticsView, modulePermissionCodes.logisticsManage],
  },
]

export function LogisticsSectionNav() {
  const { hasPermissions } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const selectedKey = location.pathname.startsWith('/logistics/returns')
    ? '/logistics/returns'
    : location.pathname.startsWith('/logistics/status')
      ? '/logistics/status'
      : location.pathname.startsWith('/logistics/carriers')
        ? '/logistics/carriers'
        : location.pathname.startsWith('/logistics/exceptions')
          ? '/logistics/exceptions'
          : '/logistics'

  return (
    <Menu
      items={sections.filter((section) => hasPermissions(section.permissions))}
      mode="horizontal"
      selectedKeys={[selectedKey]}
      onClick={({ key }) => void navigate(key)}
    />
  )
}

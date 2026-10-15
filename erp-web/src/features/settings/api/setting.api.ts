import type { SettingItem } from '../types/setting.types'
const items: SettingItem[] = [
  {
    id: 'S-001',
    name: '订单自动审核',
    code: 'order.auto-audit',
    status: '启用',
    updatedAt: '2026-08-10 08:30',
    owner: '系统管理员',
    category: '订单',
    value: '开启',
  },
  {
    id: 'S-002',
    name: '库存预警阈值',
    code: 'inventory.warning-threshold',
    status: '启用',
    updatedAt: '2026-08-09 14:00',
    owner: '系统管理员',
    category: '库存',
    value: '20',
  },
  {
    id: 'S-003',
    name: '新订单通知',
    code: 'notification.new-order',
    status: '停用',
    updatedAt: '2026-08-08 11:30',
    owner: '系统管理员',
    category: '通知',
    value: '关闭',
  },
]
export const settingApi = { getList: () => Promise.resolve(items) }

import type { InventoryItem } from '../types/inventory.types'
import { request } from '@/services/http-client'
import { isFeatureMockEnabled } from '@/services/api-mode'
const items: InventoryItem[] = [
  {
    id: 'I-001',
    name: '蓝色童车',
    code: 'A-AHKLD-BLUE',
    status: '正常',
    updatedAt: '2026-08-10 09:00',
    owner: '仓储组',
    warehouse: '美国西部仓',
    available: 680,
    inTransit: 0,
  },
  {
    id: 'I-002',
    name: '红色童车',
    code: 'A-AHKLD-RED',
    status: '预警',
    updatedAt: '2026-08-10 09:00',
    owner: '仓储组',
    warehouse: '美国东部仓',
    available: 18,
    inTransit: 120,
  },
  {
    id: 'I-003',
    name: '旅行配件套装',
    code: 'TRAVEL-SET-01',
    status: '正常',
    updatedAt: '2026-08-09 18:30',
    owner: '仓储组',
    warehouse: '国内仓',
    available: 36,
    inTransit: 0,
  },
]
const mockInventoryApi = { getList: () => Promise.resolve(items) }
const httpInventoryApi = { getList: () => request<InventoryItem[]>({ method: 'get', url: '/inventory' }) }
export const inventoryApi = isFeatureMockEnabled('inventory') ? mockInventoryApi : httpInventoryApi

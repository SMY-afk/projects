export interface InventoryItem {
  id: string
  name: string
  code: string
  status: string
  updatedAt: string
  owner: string
  warehouse: string
  available: number
  inTransit: number
}

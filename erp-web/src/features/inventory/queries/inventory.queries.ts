import { useQuery } from '@tanstack/react-query'
import { inventoryApi } from '../api/inventory.api'
export const inventoryQueryKeys = { all: ['inventory'] as const, list: () => ['inventory', 'list'] as const }
export const useInventoryListQuery = () =>
  useQuery({ queryKey: inventoryQueryKeys.list(), queryFn: inventoryApi.getList })

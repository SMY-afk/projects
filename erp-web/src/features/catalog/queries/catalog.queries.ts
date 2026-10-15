import { useQuery } from '@tanstack/react-query'
import { createCatalogApi } from '../api/catalog.api'
import type { CatalogListItem } from '../types/list-item.types'

export const createCatalogListQuery = (key: string, items: CatalogListItem[]) => () =>
  useQuery({ queryKey: ['catalog', key], queryFn: () => createCatalogApi(items).getList() })

import type { CatalogListItem } from '../types/list-item.types'

export const createCatalogApi = (items: CatalogListItem[]) => ({ getList: () => Promise.resolve(items) })

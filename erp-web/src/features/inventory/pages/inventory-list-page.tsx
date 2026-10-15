import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { InventoryList } from '../components/inventory-list'
import { useInventoryListQuery } from '../queries/inventory.queries'
export default function InventoryListPage() {
  const query = useInventoryListQuery()
  if (query.isLoading) return <PageLoading fullscreen />
  if (query.isError || !query.data) return <PageError onRetry={() => void query.refetch()} />
  return <InventoryList data={query.data} />
}

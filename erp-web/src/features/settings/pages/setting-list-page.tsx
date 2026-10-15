import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { SettingList } from '../components/setting-list'
import { useSettingListQuery } from '../queries/setting.queries'
export default function SettingListPage() {
  const query = useSettingListQuery()
  if (query.isLoading) return <PageLoading fullscreen />
  if (query.isError || !query.data) return <PageError onRetry={() => void query.refetch()} />
  return <SettingList data={query.data} />
}

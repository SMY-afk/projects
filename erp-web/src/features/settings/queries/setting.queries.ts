import { useQuery } from '@tanstack/react-query'
import { settingApi } from '../api/setting.api'
export const settingQueryKeys = { all: ['settings'] as const, list: () => ['settings', 'list'] as const }
export const useSettingListQuery = () => useQuery({ queryKey: settingQueryKeys.list(), queryFn: settingApi.getList })

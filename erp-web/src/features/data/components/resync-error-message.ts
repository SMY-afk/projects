import { HttpError } from '@/services/http-client'

export function resyncErrorMessage(error: unknown) {
  if (error instanceof HttpError) {
    if (error.status === 401) {
      return { title: '登录已失效', description: '请重新登录后再次发起同步。' }
    }
    if (error.status === 403) {
      return { title: '无同步权限', description: '当前账号没有重新同步店铺数据的权限。' }
    }
    if (error.status === 429) {
      return { title: '同步请求过于频繁', description: '请稍后再发起重新同步。' }
    }
    if (error.kind === 'timeout' || error.status === 504) {
      return { title: '同步请求超时', description: '同步任务未能及时提交，请稍后重试。' }
    }
  }
  return { title: '重新同步未提交', description: '同步服务暂时不可用，请稍后重试。' }
}

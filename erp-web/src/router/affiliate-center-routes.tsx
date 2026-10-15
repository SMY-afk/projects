import { Navigate } from 'react-router'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { AffiliateCenterPage, AffiliateCreatorDetailPage, AffiliateLiveAccountPage } from '@/router/route-pages'
import type { AppRouteMetadata } from '@/router/route-metadata'

const permissions = [modulePermissionCodes.affiliateCenterView]

export const affiliateCenterRoutes: AppRouteMetadata[] = [
  {
    key: '/affiliate-center',
    label: '联盟中心',
    path: '/affiliate-center',
    element: <Navigate replace to="/affiliate-center/creators" />,
    permissions,
    showInTopNav: true,
  },
  {
    key: '/affiliate-center/creators',
    label: '达人',
    path: '/affiliate-center/creators',
    element: <AffiliateCenterPage />,
    permissions,
  },
  {
    key: '/affiliate-center/videos',
    label: '所有视频',
    path: '/affiliate-center/videos',
    element: <AffiliateCenterPage />,
    permissions,
  },
  {
    key: '/affiliate-center/live-accounts',
    label: '联盟账号直播数据',
    path: '/affiliate-center/live-accounts',
    element: <AffiliateLiveAccountPage />,
    permissions,
  },
  {
    key: '/affiliate-center/creators/:creatorId',
    label: '达人详情',
    path: '/affiliate-center/creators/:creatorId',
    element: <AffiliateCreatorDetailPage />,
    permissions,
  },
]

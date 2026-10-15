export const modulePermissionCodes = {
  shopsView: 'shops:view',
  shopsManage: 'shops:manage',
  productsView: 'products:view',
  bestsellersView: 'bestsellers:view',
  affiliateCenterView: 'affiliate-center:view',
  ordersView: 'orders:view',
  ordersBuyerPiiView: 'orders:buyer-pii:view',
  financeView: 'finance:view',
  logisticsView: 'logistics:view',
  logisticsOperate: 'logistics:operate',
  logisticsDispatch: 'logistics:dispatch',
  logisticsManage: 'logistics:manage',
  logisticsCostView: 'logistics:cost:view',
  logisticsCostReconcile: 'logistics:cost:reconcile',
  returnsView: 'returns:view',
  returnsManage: 'returns:manage',
  returnsInspect: 'returns:inspect',
  syncTrigger: 'sync:trigger',
} as const

export type ModulePermissionCode = (typeof modulePermissionCodes)[keyof typeof modulePermissionCodes]

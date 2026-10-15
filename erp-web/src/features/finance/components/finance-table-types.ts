export interface FinanceTablePagination {
  current: number
  pageSize: number
  total: number
  onChange: (page: number, pageSize: number) => void
}

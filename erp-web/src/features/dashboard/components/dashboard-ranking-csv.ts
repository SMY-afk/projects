export function downloadRankingCsv(filename: string, headers: string[], rows: Array<Array<string | number | null>>) {
  const safeCell = (value: string | number | null) => {
    const text = value == null ? '' : String(value)
    const safe = /^[=+@\-\t\r]/.test(text) ? `'${text}` : text
    return `"${safe.replaceAll('"', '""')}"`
  }
  const lines = [headers, ...rows].map((row) => row.map(safeCell).join(','))
  const blob = new Blob([`\uFEFF${lines.join('\r\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

/** API timestamps are UTC; older rows may lack the zone suffix, so treat those as UTC too. */
export function parseUtc(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`)
}

/** "just now", "5 min ago", "3 h ago", "2 days ago"; "never" for null. */
export function timeAgo(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return 'never'
  const seconds = Math.max(0, Math.round((now.getTime() - parseUtc(value).getTime()) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.floor(hours / 24)} days ago`
}

const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const pad = (n: number) => String(n).padStart(2, '0')

/** Local "24 Nov 09:05", with the year when it is not this year ("3 Jan 2025 09:05"). */
export function formatShort(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return '—'
  const d = parseUtc(value)
  const year = d.getFullYear() === now.getFullYear() ? '' : ` ${d.getFullYear()}`
  return `${d.getDate()} ${months[d.getMonth()]}${year} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** The start and end of the local days [from] and [to] (epoch ms, as date pickers give), in UTC ISO. */
export function localDayRange(from: number | null, to: number | null): { from: string | null; to: string | null } {
  const start = (ms: number) => {
    const d = new Date(ms)
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).toISOString()
  }
  const end = (ms: number) => {
    const d = new Date(ms)
    return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59, 999).toISOString()
  }
  return { from: from === null ? null : start(from), to: to === null ? null : end(to) }
}

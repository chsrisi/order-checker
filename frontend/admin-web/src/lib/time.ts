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

/** The calendar day of a date picker's value (epoch ms, local) as "2026-11-24". */
export function dayOf(ms: number): string {
  const d = new Date(ms)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** "2026-11-24" → "24 Nov", with the year when it is not this year. A day, not an instant: no zone applies. */
export function formatDay(day: string, now: Date = new Date()): string {
  const [y = 0, m = 1, d = 1] = day.split('-').map(Number)
  return `${d} ${months[m - 1]}${y === now.getFullYear() ? '' : ` ${y}`}`
}

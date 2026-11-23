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

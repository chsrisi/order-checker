import { pickupCode, scansFor, type Order, type Outbound } from './orders'

/**
 * History search and pairing (V2_ORDERS_SPEC §13.3–13.4). The server filters which rows and
 * days come back (Q49); these helpers pair a day's orders with its scans and narrow an
 * open day to the matching pairs, with the same fields the server searches.
 */
const norm = (q: string) => q.trim().toLowerCase()

export function matchOrder(order: Order, query: string): boolean {
  const q = norm(query)
  if (!q) return true
  return [
    order.order_sn,
    pickupCode(order) ?? '',
    order.owner_user ?? '',
    order.shipping_carrier ?? '',
    order.recipient_address?.name ?? '',
    ...(order.info ?? []).map((i) => i.tracking_number ?? ''),
  ].some((t) => t.toLowerCase().includes(q))
}

export function matchScan(scan: Outbound, query: string): boolean {
  const q = norm(query)
  if (!q) return true
  return [scan.content, scan.owner_user ?? '', ...(scan.tags ?? [])].some((t) => t.toLowerCase().includes(q))
}

export interface DayPairs {
  rows: Array<{ order: Order; scans: Outbound[] }>
  /** Scans of the day that match no completed order (most often a Tokopedia package). */
  strays: Outbound[]
}

/** Each order of a day, next to the scans of that day carrying its labels. */
export function dayPairs(orders: Order[], scans: Outbound[]): DayPairs {
  const rows = orders.map((order) => ({ order, scans: scansFor(order, scans) }))
  const used = new Set(rows.flatMap((r) => r.scans.map((s) => s.id)))
  return { rows, strays: scans.filter((s) => !used.has(s.id)) }
}

/** The pairs a search keeps: a pair matches if its order or any of its scans does. */
export function matchingPairs(pairs: DayPairs, query: string): DayPairs {
  if (!norm(query)) return pairs
  return {
    rows: pairs.rows.filter((r) => matchOrder(r.order, query) || r.scans.some((s) => matchScan(s, query))),
    strays: pairs.strays.filter((s) => matchScan(s, query)),
  }
}

/** Text split around case-insensitive matches of [query], for highlighting without v-html. */
export function segments(text: string, query: string): Array<{ text: string; hit: boolean }> {
  const q = norm(query)
  if (!q || !text) return [{ text, hit: false }]
  const lower = text.toLowerCase()
  const out: Array<{ text: string; hit: boolean }> = []
  let i = 0
  for (let j = lower.indexOf(q); j !== -1; j = lower.indexOf(q, i)) {
    if (j > i) out.push({ text: text.slice(i, j), hit: false })
    out.push({ text: text.slice(j, j + q.length), hit: true })
    i = j + q.length
  }
  if (i < text.length) out.push({ text: text.slice(i), hit: false })
  return out
}

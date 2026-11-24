import type { Schemas } from '../api'
import { parseUtc } from './time'

/**
 * Order rules for the console's Orders page (V2_UX §2.4), kept as plain functions so they are
 * tested. Progress follows v1 `orders_view.dart` and the Android client's `OrderLogic.kt`.
 */
export type Order = Schemas['ShopeeOrderResponse']
export type Outbound = Schemas['OutboundResponse']

/** A `pick_item_entries_update` row (not part of the admin OpenAPI; v1 WS frame). */
export interface PickEntry {
  id: number
  sku: string
  qty: number
  order_sn?: string | null
  timestamp: string
  owner_user: string
  item_name?: string | null
}

export const UNKNOWN_SKU = 'unknown'
const bomSku = (sku: string) => sku || UNKNOWN_SKU

export type LineState = 'none' | 'partial' | 'done' | 'over'
export type OrderState = 'not_started' | 'partial' | 'done' | 'extra'

export interface SkuLine {
  sku: string
  name: string
  location: string | null
  required: number
  picked: number
  state: LineState
}

export interface Progress {
  lines: SkuLine[]
  /** Required SKUs picked exactly. */
  doneSkus: number
  /** Required SKUs with any pick entry (R4.3: the count the console shows). */
  touchedSkus: number
  requiredSkus: number
  state: OrderState
}

function lineState(picked: number, required: number): LineState {
  if (picked === 0) return 'none'
  if (picked < required) return 'partial'
  return picked === required ? 'done' : 'over'
}

/**
 * Picking progress (V2_ORDERS_DELTA R4.3): *Not started* = no pick entry for the order;
 * *Picked* = every required SKU exact; *Extra items* = a SKU picked that the order lacks
 * (wins); otherwise *Picking*. BOM lines that share a SKU are one requirement (F2): the server
 * sums per (sku, name, location), so one SKU can arrive on several lines.
 */
export function progress(order: Order, picks: PickEntry[]): Progress {
  const bom = new Map<string, { quantity: number; name: string | null; location: string | null }>()
  for (const b of order.item_list ?? []) {
    const sku = bomSku(b.component_sku)
    const prev = bom.get(sku)
    if (prev) prev.quantity += b.quantity
    else bom.set(sku, { quantity: b.quantity, name: b.component_name || null, location: b.location || null })
  }
  const mine = picks.filter((p) => p.order_sn === order.order_sn)
  const skus = new Set<string>([...bom.keys(), ...mine.map((p) => p.sku)])
  const lines = [...skus].map((sku): SkuLine => {
    const req = bom.get(sku)
    const picked = mine.filter((p) => p.sku === sku).reduce((n, p) => n + p.qty, 0)
    const required = req?.quantity ?? 0
    const name = req?.name || mine.find((p) => p.sku === sku && p.item_name)?.item_name || 'Unknown item'
    return { sku, name, location: req?.location ?? null, required, picked, state: lineState(picked, required) }
  })
  const required = lines.filter((l) => l.required > 0)
  const doneSkus = required.filter((l) => l.picked === l.required).length
  const touchedSkus = required.filter((l) => l.picked > 0).length
  let state: OrderState
  if (lines.some((l) => l.required === 0)) state = 'extra'
  else if (mine.length === 0) state = 'not_started'
  else if (doneSkus === required.length) state = 'done'
  else state = 'partial'
  return { lines, doneSkus, touchedSkus, requiredSkus: required.length, state }
}

export const orderStateLabel: Record<OrderState, string> = {
  not_started: 'Not started',
  partial: 'Picking',
  done: 'Picked',
  extra: 'Extra items',
}

export function pickupCode(order: Order): string | null {
  return order.info?.find((i) => i.pickup_code)?.pickup_code ?? null
}

/** A label as matched everywhere: trimmed, then exact (Q57; the server close does the same). */
export const normLabel = (label: string | null | undefined) => (label ?? '').trim()

/** Order SN and tracking numbers, normalised, as an outbound scan carries them. */
function labelsOf(order: Order): string[] {
  return [order.order_sn, ...(order.info ?? []).map((i) => i.tracking_number ?? '')].map(normLabel).filter(Boolean)
}

/** Label (SN or tracking number, normalised) → order SN, to show which order a scan packs. */
export function labelIndex(orders: Order[]): Map<string, string> {
  const index = new Map<string, string>()
  for (const o of orders) for (const l of labelsOf(o)) index.set(l, o.order_sn)
  return index
}

export function orderForScan(index: Map<string, string>, scan: Outbound): string | null {
  return index.get(normLabel(scan.content)) ?? null
}

/** Label → every order it matches (one label can match two orders, SPEC E5). */
export function ordersByLabel(orders: Order[]): Map<string, Order[]> {
  const index = new Map<string, Order[]>()
  for (const o of orders) for (const l of new Set(labelsOf(o))) index.set(l, [...(index.get(l) ?? []), o])
  return index
}

/** Open scans whose label is this order's SN or one of its tracking numbers. */
export function scansFor(order: Order, scans: Outbound[]): Outbound[] {
  const labels = new Set(labelsOf(order))
  return scans.filter((s) => labels.has(normLabel(s.content)))
}

/** Scans that match no ongoing order (most often a Tokopedia package, SPEC §2.1). */
export function strayScans(orders: Order[], scans: Outbound[]): Outbound[] {
  const all = new Set(orders.flatMap(labelsOf))
  return scans.filter((s) => !all.has(normLabel(s.content)))
}

export interface PackageCoverage {
  /** The order SN itself was scanned (it can't say which package). */
  bySn: boolean
  /** Packages whose own tracking number was scanned. */
  scanned: number
  total: number
}

export function packageCoverage(order: Order, scans: Outbound[]): PackageCoverage {
  const scanned = new Set(scans.map((s) => normLabel(s.content)))
  const info = order.info ?? []
  return {
    bySn: scanned.has(normLabel(order.order_sn)),
    scanned: info.filter((i) => i.tracking_number && scanned.has(normLabel(i.tracking_number))).length,
    total: info.length,
  }
}

export type PackState = 'none' | 'partial' | 'packed'

/**
 * R4.1: an order is packed when one of its labels was scanned, except a split order (2+
 * packages), which is packed only when every package's tracking number was scanned; before
 * that it is *partly packed*. An SN scan alone never completes a split order.
 */
export function packState(order: Order, scans: Outbound[]): PackState {
  const scanned = new Set(scans.map((s) => normLabel(s.content)))
  if (!labelsOf(order).some((l) => scanned.has(l))) return 'none'
  if ((order.info ?? []).length < 2) return 'packed'
  const c = packageCoverage(order, scans)
  return c.scanned < c.total ? 'partial' : 'packed'
}

/** Order SNs that count as packed (R4.1). */
export function packedOrders(orders: Order[], scans: Outbound[]): Set<string> {
  return new Set(orders.filter((o) => packState(o, scans) === 'packed').map((o) => o.order_sn))
}

/** Order SNs that are partly packed split orders (R4.1). */
export function partlyPackedOrders(orders: Order[], scans: Outbound[]): Set<string> {
  return new Set(orders.filter((o) => packState(o, scans) === 'partial').map((o) => o.order_sn))
}

/**
 * How many ongoing orders a close of these scans would mark done (preview; the server
 * decides). The server completes every order matching a closed label, partly packed or not.
 */
export function ordersClosedBy(orders: Order[], scans: Outbound[]): number {
  return orders.filter((o) => scansFor(o, scans).length > 0).length
}

/**
 * Q45: a scan with no tags at all borrows its paired order's courier, so the courier chip
 * and *Close all "courier"* include it. Stored tags never change.
 */
export function effectiveTags(scan: Outbound, index: Map<string, Order[]>): { tags: string[]; fromOrder: boolean } {
  if (scan.tags?.length) return { tags: scan.tags, fromOrder: false }
  const courier = index.get(normLabel(scan.content))?.find((o) => o.shipping_carrier)?.shipping_carrier
  return courier ? { tags: [courier], fromOrder: true } : { tags: [], fromOrder: false }
}

/** F4: late = ship-by passed while the order is still ongoing. */
export function isLate(order: Order, now: Date = new Date()): boolean {
  return parseUtc(order.ship_by).getTime() < now.getTime()
}

export type Category = 'all' | 'instant' | 'regular'

/** v1 category filter: "Instant / Sameday" by carrier name, everything else is regular. */
export function isInstant(order: Order): boolean {
  const carrier = (order.shipping_carrier ?? '').toLowerCase()
  return carrier.includes('instant') || carrier.includes('same day') || carrier.includes('sameday')
}

export interface OrderFilter {
  category: Category
  courier: string | null
  hideDone: boolean
  query: string
}

export function matchesFilter(
  order: Order,
  f: OrderFilter,
  ctx: { packed: Set<string>; ticked: Set<string>; picks: PickEntry[] },
): boolean {
  if (f.category === 'instant' && !isInstant(order)) return false
  if (f.category === 'regular' && isInstant(order)) return false
  if (f.courier && order.shipping_carrier !== f.courier) return false
  if (f.hideDone && (ctx.packed.has(order.order_sn) || ctx.ticked.has(order.order_sn))) return false
  const q = f.query.trim().toLowerCase()
  if (!q) return true
  const haystack = [
    order.order_sn,
    pickupCode(order) ?? '',
    order.owner_user ?? '',
    order.recipient_address?.name ?? '',
    ...(order.info ?? []).map((i) => i.tracking_number ?? ''),
    ...(order.item_list ?? []).flatMap((b) => [b.component_sku, b.component_name ?? '']),
    ...ctx.picks.filter((p) => p.order_sn === order.order_sn).flatMap((p) => [p.sku, p.item_name ?? '']),
  ]
  return haystack.some((text) => text.toLowerCase().includes(q))
}

/** v1 grouping: Ready to ship, then Processed (Retry ship counts as Processed), then the rest. */
export function statusGroup(order: Order): string {
  return order.status === 'RETRY_SHIP' ? 'PROCESSED' : order.status
}

const groupOrder = ['READY_TO_SHIP', 'PROCESSED']

/**
 * v1 grouping: Ready to ship, then Processed (Retry ship counts as Processed), then the rest.
 * Inside a group, packed orders go last (R3), then the soonest ship-by first.
 */
export function groupByStatus(orders: Order[], packed: Set<string> = new Set()): Array<{ status: string; orders: Order[] }> {
  const groups = new Map<string, Order[]>()
  for (const o of orders) {
    const key = statusGroup(o)
    groups.set(key, [...(groups.get(key) ?? []), o])
  }
  const rank = (s: string) => (groupOrder.includes(s) ? groupOrder.indexOf(s) : groupOrder.length)
  const sunk = (o: Order) => (packed.has(o.order_sn) ? 1 : 0)
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([status, list]) => ({
      status,
      orders: [...list].sort((a, b) => sunk(a) - sunk(b) || a.ship_by.localeCompare(b.ship_by) || a.order_sn.localeCompare(b.order_sn)),
    }))
}

export function statusLabel(status: string): string {
  return status
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/**
 * Scan counts per tag for the close review; untagged scans count under "No tag". [tagsOf]
 * lets the review count a borrowed courier (Q45, see [effectiveTags]).
 */
export function countByTag(scans: Outbound[], tagsOf: (s: Outbound) => string[] = (s) => s.tags ?? []): Array<{ tag: string; count: number }> {
  const counts = new Map<string, number>()
  for (const s of scans) {
    const own = tagsOf(s)
    for (const t of own.length ? own : ['No tag']) counts.set(t, (counts.get(t) ?? 0) + 1)
  }
  return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([tag, count]) => ({ tag, count }))
}

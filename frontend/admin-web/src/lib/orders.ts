import type { Schemas } from '../api'

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
  doneSkus: number
  requiredSkus: number
  state: OrderState
}

function lineState(picked: number, required: number): LineState {
  if (picked === 0) return 'none'
  if (picked < required) return 'partial'
  return picked === required ? 'done' : 'over'
}

export function progress(order: Order, picks: PickEntry[]): Progress {
  const bom = order.item_list ?? []
  const mine = picks.filter((p) => p.order_sn === order.order_sn)
  const skus = new Set<string>([...bom.map((b) => bomSku(b.component_sku)), ...mine.map((p) => p.sku)])
  const lines = [...skus].map((sku): SkuLine => {
    const req = bom.find((b) => bomSku(b.component_sku) === sku)
    const picked = mine.filter((p) => p.sku === sku).reduce((n, p) => n + p.qty, 0)
    const required = req?.quantity ?? 0
    const name = req?.component_name || mine.find((p) => p.sku === sku && p.item_name)?.item_name || 'Unknown item'
    return { sku, name, location: req?.location || null, required, picked, state: lineState(picked, required) }
  })
  const doneSkus = lines.filter((l) => l.required === l.picked).length
  let state: OrderState
  if (lines.some((l) => l.required === 0)) state = 'extra'
  else if (doneSkus === 0) state = 'not_started'
  else if (doneSkus < bom.length) state = 'partial'
  else state = 'done'
  return { lines, doneSkus, requiredSkus: bom.length, state }
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

/** Order SN and tracking numbers, trimmed and lower-cased, as an outbound scan carries them. */
function labelsOf(order: Order): string[] {
  const labels = [order.order_sn, ...(order.info ?? []).map((i) => i.tracking_number ?? '')]
  return labels.map((l) => l.trim().toLowerCase()).filter(Boolean)
}

/** Label (SN or tracking number, normalised) → order SN, to show which order a scan packs. */
export function labelIndex(orders: Order[]): Map<string, string> {
  const index = new Map<string, string>()
  for (const o of orders) for (const l of labelsOf(o)) index.set(l, o.order_sn)
  return index
}

export function orderForScan(index: Map<string, string>, scan: Outbound): string | null {
  return index.get(scan.content.trim().toLowerCase()) ?? null
}

/** Order SNs whose label (SN or tracking number) was scanned at outbound: "Packed" (v1 rule). */
export function packedOrders(orders: Order[], scans: Outbound[]): Set<string> {
  const scanned = new Set(scans.map((s) => s.content.trim().toLowerCase()))
  return new Set(orders.filter((o) => labelsOf(o).some((l) => scanned.has(l))).map((o) => o.order_sn))
}

/** How many open orders a close of these scans would mark done (preview; the server decides). */
export function ordersClosedBy(orders: Order[], scans: Outbound[]): number {
  return packedOrders(orders, scans).size
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

export function groupByStatus(orders: Order[]): Array<{ status: string; orders: Order[] }> {
  const groups = new Map<string, Order[]>()
  for (const o of orders) {
    const key = statusGroup(o)
    groups.set(key, [...(groups.get(key) ?? []), o])
  }
  const rank = (s: string) => (groupOrder.includes(s) ? groupOrder.indexOf(s) : groupOrder.length)
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([status, list]) => ({
      status,
      orders: [...list].sort((a, b) => a.ship_by.localeCompare(b.ship_by) || a.order_sn.localeCompare(b.order_sn)),
    }))
}

export function statusLabel(status: string): string {
  return status
    .toLowerCase()
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Scan counts per tag for the close review; untagged scans count under "No tag". */
export function countByTag(scans: Outbound[]): Array<{ tag: string; count: number }> {
  const counts = new Map<string, number>()
  for (const s of scans) {
    const tags = s.tags?.length ? s.tags : ['No tag']
    for (const t of tags) counts.set(t, (counts.get(t) ?? 0) + 1)
  }
  return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([tag, count]) => ({ tag, count }))
}
